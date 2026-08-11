#!/usr/bin/env python3
"""Build real citation-aware variants from the papers with unique OpenAlex IDs.

The input order is preserved. Only papers with a confident OpenAlex identity are
included, so every citation edge can be traced to a provider work ID. Local
metadata and local embeddings remain available for variant assignment.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_graph.embeddings import HashEmbeddingEncoder
from paper_graph.graph_builder import PaperGraphBuilder
from paper_graph.open_academic import OpenAcademicClient


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return {str(row["id"]): row for row in jsonl(path)}


def save_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                         for row in sorted(cache.values(), key=lambda item: str(item["id"]))), encoding="utf-8")


def enrich_openalex(client: OpenAcademicClient, local: dict[str, Any], manifest_row: dict[str, Any],
                    cache: dict[str, dict[str, Any]], delay: float) -> dict[str, Any]:
    openalex_id = str(manifest_row["openalex"]["openalex_id"])
    provider_id = f"openalex:{openalex_id}"
    if provider_id not in cache:
        if delay:
            time.sleep(delay)
        work = client.openalex_work(provider_id)
        cache[provider_id] = work
    work = cache[provider_id]
    metadata = dict(local.get("metadata") or {})
    provider_metadata = dict(work.get("metadata") or {})
    # Keep the local arXiv identity as the graph key while retaining the
    # provider identity and explicit OpenAlex references.
    merged = dict(local)
    merged["metadata"] = {
        **metadata,
        **provider_metadata,
        "openalex_id": provider_id,
        "identity_status": "matched",
        "identity_source": "parsed_manifest",
        "openalex_references": list(provider_metadata.get("references") or []),
        "verified_relations": True,
    }
    if work.get("abstract"):
        merged["abstract"] = work["abstract"]
    if work.get("authors"):
        merged["authors"] = work["authors"]
    if work.get("year"):
        merged["year"] = work["year"]
    return merged


def attach_known_citations(papers: list[dict[str, Any]], by_openalex: dict[str, str]) -> None:
    for paper in papers:
        metadata = paper.setdefault("metadata", {})
        references = []
        for provider_reference in metadata.get("openalex_references", []):
            local_id = by_openalex.get(str(provider_reference))
            if local_id and local_id != paper["id"]:
                references.append(local_id)
        metadata["references"] = sorted(set(references))
        metadata["citation_edge_scope"] = "matched_openalex_papers"


def relation_score(candidate: dict[str, Any], existing: list[dict[str, Any]], threshold: float,
                   builder: PaperGraphBuilder) -> tuple[bool, str, float]:
    candidate_id = str(candidate["id"])
    existing_ids = {str(item["id"]) for item in existing}
    if any(candidate_id in (item.get("metadata") or {}).get("references", []) for item in existing):
        return True, "openalex_explicit_citation", 1.0
    candidate_references = set((candidate.get("metadata") or {}).get("references", []))
    if candidate_references & existing_ids:
        return True, "openalex_explicit_citation", 1.0
    _, edges = builder.build([*existing, candidate], top_k=max(8, len(existing)), minimum_embedding_score=0.05)
    incident = [edge for edge in edges if candidate_id in {edge.source, edge.target}]
    score = max((float(edge.weight or 0.0) for edge in incident if edge.relation == "EMBEDDING_SIMILAR_TO"), default=0.0)
    if score >= threshold:
        return True, "local_embedding", score
    return False, "new_variant", score


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default=None, help="only process one secondary topic")
    parser.add_argument("--threshold", type=float, default=0.55)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument("--manifest", type=Path, default=ROOT / "docs/generated/parsed-paper-manifest/papers.jsonl")
    parser.add_argument("--graph-root", type=Path, default=ROOT / "docs/generated/digest-topic-graphs/three-ai-v2")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/generated/openalex-integrated-test")
    args = parser.parse_args()

    manifest = {str(row["paper_id"]): row for row in jsonl(args.manifest)}
    client = OpenAcademicClient()
    cache_path = args.output / "openalex_works.jsonl"
    cache = load_cache(cache_path)
    encoder = HashEmbeddingEncoder()
    builder = PaperGraphBuilder(encoder=encoder)
    output_graphs = args.output / "graphs"
    decisions: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []
    matched_count = 0

    for graph_path in sorted((args.graph_root / "graphs").glob("topic_*.json")):
        topic_id = graph_path.stem.removeprefix("topic_")
        if args.topic and topic_id != args.topic:
            continue
        source = json.loads(graph_path.read_text(encoding="utf-8"))
        local_rows = []
        for node in source.get("nodes", []):
            row = manifest.get(str(node.get("id")))
            if row and (row.get("openalex") or {}).get("status") == "matched":
                local_rows.append((dict(node), row))
        if not local_rows:
            continue
        papers = [enrich_openalex(client, node, row, cache, args.delay) for node, row in local_rows]
        matched_count += len(papers)
        by_openalex = {str((paper.get("metadata") or {}).get("openalex_id")): str(paper["id"]) for paper in papers}
        attach_known_citations(papers, by_openalex)

        variants: list[dict[str, Any]] = []
        for position, candidate in enumerate(papers, 1):
            best = None
            best_basis = "new_variant"
            best_score = 0.0
            for variant in variants:
                merge, basis, score = relation_score(candidate, variant["nodes"], args.threshold, builder)
                if merge and (best is None or score > best_score):
                    best, best_basis, best_score = variant, basis, score
            if best is None:
                best = {"nodes": [candidate], "seed_ids": [str(candidate["id"])]}
                variants.append(best)
                decisions.append({"topic_id": topic_id, "position": position, "paper_id": candidate["id"],
                                  "decision": "new_graph", "basis": "initial_seed", "variant_seed_ids": best["seed_ids"]})
            else:
                best["nodes"].append(candidate)
                decisions.append({"topic_id": topic_id, "position": position, "paper_id": candidate["id"],
                                  "decision": "merge", "basis": best_basis, "score": round(best_score, 6),
                                  "variant_seed_ids": sorted(best["seed_ids"])})

        for variant_number, variant in enumerate(variants, 1):
            records, edges = builder.build(variant["nodes"], top_k=20, minimum_embedding_score=0.05)
            graph = builder.response(records, seed=variant["seed_ids"][0], seeds=variant["seed_ids"], top_k=20)
            graph.update({"category": topic_id, "variant_number": variant_number,
                          "identity_scope": "67_unique_openalex_manifest_matches",
                          "core_seed_ids": variant["seed_ids"],
                          "member_ids": [str(item["id"]) for item in records],
                          "provenance": {"openalex_verified": True, "local_embedding": True,
                                         "external_expansion": False}})
            path = output_graphs / topic_id / f"variant-{variant_number:03d}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
            index.append({"topic_id": topic_id, "variant_id": path.stem, "node_count": len(records),
                          "edge_count": len(edges), "member_ids": graph["member_ids"]})

    save_cache(cache_path, cache)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "variant_decisions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in decisions), encoding="utf-8")
    (args.output / "variant_index.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in index), encoding="utf-8")
    summary = {"matched_papers_processed": matched_count, "topics": len({row["topic_id"] for row in index}),
               "variants": len(index), "decisions": len(decisions),
               "merge_count": sum(row["decision"] == "merge" for row in decisions),
               "new_graph_count": sum(row["decision"] == "new_graph" for row in decisions),
               "openalex_citation_edges_are_explicit_only": True}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
