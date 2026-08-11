#!/usr/bin/env python3
"""Build static topic graphs from the identity-resolved OpenAlex candidate JSONL.

This is intentionally network-free: all nodes come from the completed candidate
query, and edges are generated locally from citation-independent metadata and
text embeddings. The source candidate file is never modified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from paper_graph.graph_builder import PaperGraphBuilder


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("openalex_id"):
                rows.append(value)
    return rows


def node(row: dict[str, Any], topic_id: str) -> dict[str, Any]:
    paper_id = str(row["openalex_id"])
    metadata = {
        "provider": "openalex",
        "openalex_id": paper_id,
        "doi": row.get("doi"),
        "arxiv_id": row.get("arxiv_id"),
        "identity_type": row.get("identity_type"),
        "identity_value": row.get("identity_value"),
        "topic_id": topic_id,
        "source": "topic-seed-candidates-2016-v1",
    }
    return {
        "id": paper_id,
        "title": row.get("title") or "Untitled paper",
        "authors": row.get("authors") or [],
        "year": row.get("year"),
        "url": row.get("url") or f"https://openalex.org/{paper_id.rsplit(':', 1)[-1]}",
        "abstract": "",
        "keywords": row.get("matched_keywords") or [],
        "citation_count": int(row.get("citation_count") or 0),
        "role": "candidate",
        "is_seed": False,
        "metadata": metadata,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("docs/generated/topic-seed-candidates-2016-v1.jsonl"))
    parser.add_argument("--output-root", type=Path, default=Path("docs/generated/candidate-topic-graphs-2016-v1"))
    parser.add_argument("--topic", default=None)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--minimum-embedding-score", type=float, default=0.12)
    args = parser.parse_args()
    if args.top_k < 1 or not 0 <= args.minimum_embedding_score <= 1:
        raise SystemExit("top-k must be positive and embedding score must be between 0 and 1")

    rows = read_jsonl(args.input)
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for topic_id in row.get("topic_ids", []):
            by_topic.setdefault(str(topic_id), []).append(row)
    if args.topic:
        by_topic = {args.topic: by_topic.get(args.topic, [])}
        if not by_topic[args.topic]:
            raise SystemExit(f"topic not found or has no candidates: {args.topic}")

    builder = PaperGraphBuilder()
    topic_summary: list[dict[str, Any]] = []
    args.output_root.mkdir(parents=True, exist_ok=True)
    for topic_id in sorted(by_topic):
        unique: dict[str, dict[str, Any]] = {}
        for row in by_topic[topic_id]:
            unique.setdefault(str(row["openalex_id"]), row)
        nodes = [node(row, topic_id) for row in unique.values()]
        records, edges = builder.build(nodes, top_k=args.top_k,
                                       minimum_embedding_score=args.minimum_embedding_score)
        node_ids = {str(item["id"]) for item in records}
        graph = {
            "schema_version": "paper_graph_candidate_topic_v1",
            "graph_id": f"topic-{topic_id}",
            "topic_id": topic_id,
            "nodes": records,
            "edges": [
                {"source": edge.source, "target": edge.target, "relation": edge.relation,
                 "weight": edge.weight, "metadata": edge.metadata}
                for edge in edges if edge.source in node_ids and edge.target in node_ids
            ],
            "stats": {
                "node_count": len(records),
                "edge_count": len(edges),
                "edge_counts_by_relation": {},
                "candidate_count": len(records),
                "min_publication_year": min((r.get("year") for r in rows if isinstance(r.get("year"), int)), default=None),
            },
            "provenance": {
                "source": str(args.input),
                "network_expansion": False,
                "identity_rule": "doi_or_arxiv_id_plus_openalex_id",
                "minimum_embedding_score": args.minimum_embedding_score,
                "top_k": args.top_k,
            },
        }
        counts: dict[str, int] = {}
        for edge in graph["edges"]:
            counts[edge["relation"]] = counts.get(edge["relation"], 0) + 1
        graph["stats"]["edge_counts_by_relation"] = counts
        topic_dir = args.output_root / topic_id
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "graph.json").write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
        topic_summary.append({"topic_id": topic_id, "node_count": len(records),
                              "edge_count": len(graph["edges"]), "edge_counts": counts})
        print(json.dumps(topic_summary[-1], ensure_ascii=False), flush=True)

    summary = {"schema_version": "paper_graph_candidate_topic_v1", "topic_count": len(topic_summary),
               "source_candidate_count": len(rows), "topics": topic_summary,
               "output_root": str(args.output_root), "network_expansion": False}
    (args.output_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"topic_count": len(topic_summary), "source_candidate_count": len(rows),
                      "output_root": str(args.output_root)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
