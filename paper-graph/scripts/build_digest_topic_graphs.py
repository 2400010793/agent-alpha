#!/usr/bin/env python3
"""Generate versioned quantitative-research topic paper graphs offline.

The stable 12/54 taxonomy is reused from Paper Digest and can be extended by an
additive, versioned Paper Graph overlay.  Only local JSONL inputs are read.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PAPER_GRAPH_ROOT = Path(__file__).resolve().parents[1]
DIGEST_ROOT = PAPER_GRAPH_ROOT.parent / "my-paper-digest-new2"
TAXONOMY_FILE = DIGEST_ROOT / "src" / "taxonomy" / "extract_topics.py"
sys.path.insert(0, str(PAPER_GRAPH_ROOT / "src"))
from paper_graph.graph_builder import PaperGraphBuilder  # noqa: E402
from paper_graph.taxonomy import load_extension, merge_taxonomy  # noqa: E402


DEFAULT_TAXONOMY_EXTENSION = PAPER_GRAPH_ROOT / "configs" / "quant_research_taxonomy_extensions_v2.json"


def load_base_taxonomy() -> tuple[dict[str, Any], ...]:
    spec = importlib.util.spec_from_file_location("digest_taxonomy", TAXONOMY_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load taxonomy: {TAXONOMY_FILE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    taxonomy = tuple(module.TAXONOMY)
    first_count = len(taxonomy)
    second_count = sum(len(item["children"]) for item in taxonomy)
    if first_count != 12 or second_count != 54:
        raise ValueError(f"legacy compatibility base must be 12/54, got {first_count}/{second_count}")
    return taxonomy


def load_taxonomy(extension_path: Path | None) -> tuple[tuple[dict[str, Any], ...], Any]:
    extension = load_extension(extension_path) if extension_path is not None else None
    return merge_taxonomy(load_base_taxonomy(), extension)


def read_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            key = str(row.get("arxiv_id") or row.get("id") or row.get("title") or "").strip()
            if not key:
                continue
            old = merged.get(key, {})
            merged[key] = {**old, **{k: v for k, v in row.items() if v not in (None, "", [], {})}}
    return list(merged.values())


def read_manifest(path: Path) -> dict[str, dict[str, Any]]:
    """Read the compact classification manifest keyed by canonical arXiv ID."""
    if not path.exists():
        raise FileNotFoundError(path)
    result: dict[str, dict[str, Any]] = {}
    for row in read_jsonl([path]):
        value = str(row.get("paper_id") or row.get("arxiv_id") or "").strip()
        value = re.sub(r"^arxiv:", "", value, flags=re.I).split("v", 1)[0]
        if value:
            result[f"arxiv:{value}"] = row
    return result



def has_complete_three_ai(row: dict[str, Any]) -> bool:
    """Return whether a row contains all three required analysis stages."""
    def present(keys: tuple[str, ...]) -> bool:
        return any(row.get(key) not in (None, "", [], {}) for key in keys)

    return present(("llm_reading_note", "reading_note", "reading_note_v1")) and present(
        ("paper_hf_factors", "article_opinions", "opinion_analysis")
    ) and present(("llm_faithfulness_audit", "faithfulness_audit", "llm_opinion_faithfulness_audit"))


def text_for(row: dict[str, Any]) -> str:
    values = [row.get("title"), row.get("summary"), row.get("abstract"), row.get("tags"),
              row.get("keywords"), row.get("research_topic_category"), row.get("research_topic_label"),
              row.get("structured_summary"), row.get("llm_reading_note"), row.get("evidence_pack")]
    return " ".join(str(value or "") for value in values).casefold()


def canonical_id(row: dict[str, Any]) -> str:
    value = str(row.get("arxiv_id") or row.get("id") or "").strip()
    value = re.sub(r"^arxiv:", "", value, flags=re.I).split("v", 1)[0]
    if value:
        return f"arxiv:{value}"
    digest = hashlib.sha1(str(row.get("title", "")).encode("utf-8")).hexdigest()[:16]
    return f"digest:{digest}"


def classify(row: dict[str, Any], taxonomy: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    text = text_for(row)
    matches: list[dict[str, Any]] = []
    for parent in taxonomy:
        for child_id, child_values in parent["children"].items():
            label, *keywords = child_values
            hits = [term for term in keywords if str(term).casefold() in text]
            if hits:
                matches.append({"parent_id": parent["id"], "parent_label": parent["label"],
                                "id": child_id, "label": label, "hits": hits, "score": len(hits)})
    return sorted(matches, key=lambda item: (-item["score"], item["id"]))


def make_graph(topic: dict[str, Any], rows: list[dict[str, Any]], classifications: dict[str, list[dict[str, Any]]],
               min_score: float, manifest: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    child_id = topic["id"]
    selected = [row for row in rows if any(item["id"] == child_id for item in classifications[canonical_id(row)])]
    nodes = []
    for row in selected:
        node_id = canonical_id(row)
        raw_keywords = row.get("keywords") or row.get("tags") or []
        if isinstance(raw_keywords, str):
            raw_keywords = [raw_keywords]
        compact = (manifest or {}).get(node_id, {})
        openalex = compact.get("openalex") or {}
        metadata = {"source": "my-paper-digest-new2", "topic": child_id,
                    "classification": classifications[node_id]}
        if openalex.get("status") == "matched":
            metadata["openalex"] = openalex
        nodes.append({"id": node_id, "title": row.get("title") or compact.get("title") or node_id, "year": row.get("year") or openalex.get("year"),
                      "authors": row.get("authors", []), "abstract": row.get("abstract") or row.get("summary", ""),
                      "role": "related", "is_seed": False, "metadata": metadata})
    _, paper_edges = PaperGraphBuilder().build(nodes, top_k=20, minimum_embedding_score=min_score)
    edges = [{"source": edge.source, "target": edge.target, "relation": edge.relation,
              "weight": edge.weight, "metadata": edge.metadata} for edge in paper_edges]
    return {"category": child_id, "parent": {"id": topic["parent_id"], "label": topic["parent_label"]},
            "label": topic["label"], "nodes": nodes, "edges": edges,
            "stats": {"node_count": len(nodes), "edge_count": len(edges)},
            "provenance": {"source": "my-paper-digest-new2", "taxonomy": "TAXONOMY in src/taxonomy/extract_topics.py",
                           "embedding_model": "hash-baseline", "edge_semantics": "paper-graph embedding/author edges; no citation is inferred"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=PAPER_GRAPH_ROOT / "docs" / "generated" / "digest-topic-graphs")
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--complete-only", action="store_true", help="keep only papers with all three AI stages")
    parser.add_argument("--manifest", type=Path, default=None,
                        help="compact parsed-paper manifest; its topic_matches are authoritative")
    parser.add_argument("--taxonomy-extension", type=Path, default=DEFAULT_TAXONOMY_EXTENSION,
                        help="additive taxonomy overlay; defaults to the candidate v2 expansion")
    parser.add_argument("--legacy-taxonomy", action="store_true",
                        help="disable the overlay and reproduce the stable 12/54 taxonomy")
    args = parser.parse_args()
    inputs = args.input or [DIGEST_ROOT / "data" / "analysis_archive.jsonl"]
    taxonomy, taxonomy_summary = load_taxonomy(
        None if args.legacy_taxonomy else args.taxonomy_extension
    )
    rows = read_jsonl(inputs)
    if args.complete_only:
        rows = [row for row in rows if has_complete_three_ai(row)]
    compact_manifest = read_manifest(args.manifest) if args.manifest else {}
    classifications: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        paper_id = canonical_id(row)
        compact = compact_manifest.get(paper_id)
        if compact is not None:
            classifications[paper_id] = [
                {"parent_id": match.get("parent_id"), "parent_label": "", "id": match["topic_id"],
                 "label": match.get("label", ""), "hits": match.get("matched_terms", []),
                 "score": match.get("score", 0)}
                for match in (compact.get("topic_matches") or [])[:2]
                if match.get("topic_id")
            ]
        else:
            classifications[paper_id] = classify(row, taxonomy)[:2]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    graphs_dir = args.output_dir / "graphs"
    graphs_dir.mkdir(exist_ok=True)
    output_schema = "digest_topic_graphs_v1" if args.legacy_taxonomy else "digest_topic_graphs_v2"
    manifest = {"schema_version": output_schema,
                "taxonomy_version": taxonomy_summary.taxonomy_version,
                "taxonomy_status": taxonomy_summary.status,
                "first_level_count": taxonomy_summary.first_level_count,
                "second_level_count": taxonomy_summary.second_level_count,
                "inputs": [str(path) for path in inputs],
                "first_levels": []}
    all_topics: list[dict[str, Any]] = []
    for parent in taxonomy:
        children = []
        for child_id, values in parent["children"].items():
            child = {"parent_id": parent["id"], "parent_label": parent["label"], "id": child_id, "label": values[0], "keywords": list(values[1:])}
            children.append(child)
            all_topics.append(child)
        manifest["first_levels"].append({"id": parent["id"], "label": parent["label"], "children": children})
    (args.output_dir / "taxonomy.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    classified_path = args.output_dir / "papers_classified.jsonl"
    classified_path.write_text("\n".join(json.dumps({"id": canonical_id(row), "title": row.get("title", ""), "matches": classifications[canonical_id(row)]}, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    graph_stats = {}
    for topic in all_topics:
        graph = make_graph(topic, rows, classifications, args.min_score, compact_manifest)
        (graphs_dir / f"topic_{topic['id']}.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        graph_stats[topic["id"]] = graph["stats"]
    summary = {"schema_version": output_schema,
               "taxonomy_version": taxonomy_summary.taxonomy_version,
               "taxonomy_status": taxonomy_summary.status,
               "paper_count": len(rows),
               "first_level_count": taxonomy_summary.first_level_count,
               "second_level_count": taxonomy_summary.second_level_count,
               "matched_paper_count": sum(bool(value) for value in classifications.values()),
               "papers_without_topic": sum(not value for value in classifications.values()),
               "classification_source": "compact_manifest" if args.manifest else "keyword_fallback",
               "topic_counts": Counter(item["id"] for values in classifications.values() for item in values),
               "graphs": graph_stats}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": str(args.output_dir), "paper_count": len(rows),
                      "taxonomy_version": taxonomy_summary.taxonomy_version,
                      "first_level_count": taxonomy_summary.first_level_count,
                      "second_level_count": taxonomy_summary.second_level_count}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
