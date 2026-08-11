#!/usr/bin/env python3
"""Build an auditable paper-to-graph index for downstream digest processing.

The index is the stable bridge between paper identity, topic/variant membership,
OpenAlex identity, and graph importance. It performs no network access.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def canonical_arxiv(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"^arxiv:", "", text, flags=re.I).split("v", 1)[0]
    return f"arxiv:{text}" if text else None


def identity(node: dict[str, Any], manifest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    metadata = node.get("metadata") or {}
    openalex = metadata.get("openalex") or {}
    paper_id = str(node.get("id") or "")
    local_id = canonical_arxiv(metadata.get("local_id")) or canonical_arxiv(paper_id)
    compact = manifest.get(local_id or "", {})
    compact_openalex = compact.get("openalex") or {}
    openalex_id = str(openalex.get("openalex_id") or compact_openalex.get("openalex_id") or "")
    if openalex_id and not openalex_id.startswith("openalex:"):
        openalex_id = f"openalex:{openalex_id}"
    doi = str(openalex.get("doi") or compact_openalex.get("doi") or "").strip()
    doi = re.sub(r"^https?://doi.org/", "", doi, flags=re.I).lower()
    return {
        "paper_id": local_id or paper_id,
        "arxiv_id": local_id,
        "openalex_id": openalex_id or None,
        "doi": doi or None,
        "title": node.get("title") or compact.get("title") or "",
        "year": node.get("year") or compact_openalex.get("year"),
        "url": compact.get("url") or node.get("url"),
        "source": metadata.get("source") or "my-paper-digest-new2",
    }


def edge_weight(edge: dict[str, Any]) -> float:
    return float(edge.get("weight") or 0.0)


def build_topic_index(graph_root: Path, manifest_path: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    manifest: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(manifest_path):
        key = canonical_arxiv(row.get("paper_id") or row.get("arxiv_id"))
        if key:
            manifest[key] = row
    papers: dict[str, dict[str, Any]] = {}
    topic_rows: list[dict[str, Any]] = []
    for graph_path in sorted((graph_root / "graphs").glob("topic_*.json")):
        graph = read_json(graph_path)
        topic_id = str(graph.get("category") or graph_path.stem.removeprefix("topic_"))
        nodes = graph.get("nodes", [])
        degree: defaultdict[str, float] = defaultdict(float)
        edge_count: defaultdict[str, int] = defaultdict(int)
        for edge in graph.get("edges", []):
            source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
            weight = max(0.0, edge_weight(edge))
            for paper_id in (source, target):
                degree[paper_id] += weight
                edge_count[paper_id] += 1
        max_degree = max(degree.values(), default=0.0)
        for node in nodes:
            node_id = str(node.get("id") or "")
            if not node_id:
                continue
            ident = identity(node, manifest)
            paper_key = ident["paper_id"] or node_id
            record = papers.setdefault(paper_key, {**ident, "paper_id": paper_key, "graph_memberships": []})
            record["graph_memberships"].append({
                "topic_id": topic_id,
                "variant_ids": [],
                "role": node.get("role", "related"),
                "is_seed": bool(node.get("is_seed")),
                "topic_score": next((item.get("score") for item in (node.get("metadata") or {}).get("classification", [])
                                      if item.get("id") == topic_id), None),
                "edge_count": edge_count.get(node_id, 0),
                "weighted_degree": round(degree.get(node_id, 0.0), 6),
                "importance": round(degree.get(node_id, 0.0) / max_degree, 6) if max_degree else 0.0,
                "graph_path": str(graph_path.relative_to(graph_root)),
            })
        topic_rows.append({"topic_id": topic_id, "graph_path": str(graph_path.relative_to(graph_root)),
                           "node_count": len(nodes), "edge_count": len(graph.get("edges", []))})

    variants_root = graph_root / "variants"
    for variant_path in sorted(variants_root.glob("*/*.json")) if variants_root.exists() else []:
        topic_id = variant_path.parent.name
        variant = read_json(variant_path)
        variant_id = str(variant.get("variant_id") or variant_path.stem)
        for node in variant.get("nodes", []):
            ident = identity(node, manifest)
            paper_key = ident["paper_id"] or str(node.get("id") or "")
            record = papers.setdefault(paper_key, {**ident, "paper_id": paper_key, "graph_memberships": []})
            memberships = [item for item in record["graph_memberships"] if item.get("topic_id") == topic_id]
            if memberships:
                for item in memberships:
                    item.setdefault("variant_ids", []).append(variant_id)
            else:
                record["graph_memberships"].append({"topic_id": topic_id, "variant_ids": [variant_id],
                                                     "role": node.get("role", "related"), "is_seed": bool(node.get("is_seed")),
                                                     "topic_score": None, "edge_count": 0, "weighted_degree": 0.0,
                                                     "importance": 0.0, "graph_path": str(variant_path.relative_to(graph_root))})
    for record in papers.values():
        for membership in record["graph_memberships"]:
            membership["variant_ids"] = sorted(set(membership.get("variant_ids", [])))
        record["topic_ids"] = sorted({item["topic_id"] for item in record["graph_memberships"]})
        record["graph_count"] = len(record["graph_memberships"])
        record["highest_importance"] = max((item["importance"] for item in record["graph_memberships"]), default=0.0)
        record["digest_lookup"] = {"paper_id": record["paper_id"], "topic_ids": record["topic_ids"],
                                    "primary_topic": max(record["graph_memberships"],
                                                          key=lambda item: (item.get("importance", 0.0), item.get("topic_score") or 0),
                                                          default={}).get("topic_id")}
    return papers, topic_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-root", type=Path, default=Path("docs/generated/digest-topic-graphs/three-ai-v2"))
    parser.add_argument("--manifest", type=Path, default=Path("docs/generated/parsed-paper-manifest/papers.jsonl"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or args.graph_root / "paper_graph_index.jsonl"
    papers, topics = build_topic_index(args.graph_root, args.manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in sorted(papers.values(), key=lambda row: row["paper_id"])), encoding="utf-8")
    topic_output = output.with_name("topic_graph_index.json")
    topic_output.write_text(json.dumps({"schema_version": "paper_graph_topic_index_v1", "topics": topics,
                                        "paper_count": len(papers), "topic_count": len(topics)}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"paper_count": len(papers), "topic_count": len(topics), "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
