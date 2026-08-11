#!/usr/bin/env python3
"""Build a de-duplicated Paper Digest queue from a paper-graph index.

A paper may belong to several topic graphs or variants, but it is emitted once.
All memberships remain on that one queue item for downstream fan-out.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_queue(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicate paper rows and deduplicate memberships."""
    by_paper: dict[str, dict[str, Any]] = {}
    for row in rows:
        paper_id = str(row.get("paper_id") or row.get("arxiv_id") or "").strip()
        if not paper_id:
            continue
        item = by_paper.setdefault(paper_id, {
            key: row.get(key) for key in
            ("paper_id", "arxiv_id", "openalex_id", "doi", "title", "year", "url", "source")
        })
        item.setdefault("graph_memberships", [])
        for key in ("arxiv_id", "openalex_id", "doi", "title", "year", "url", "source"):
            if not item.get(key) and row.get(key):
                item[key] = row[key]
        item["graph_memberships"].extend(row.get("graph_memberships") or [])

    queue: list[dict[str, Any]] = []
    for item in by_paper.values():
        memberships: dict[tuple[str, str], dict[str, Any]] = {}
        for raw in item["graph_memberships"]:
            topic_id = str(raw.get("topic_id") or "")
            if not topic_id:
                continue
            key = (topic_id, str(raw.get("graph_path") or ""))
            current = memberships.setdefault(key, {
                "topic_id": topic_id,
                "variant_ids": [],
                "role": raw.get("role", "related"),
                "is_seed": False,
                "topic_score": raw.get("topic_score"),
                "edge_count": 0,
                "weighted_degree": 0.0,
                "importance": 0.0,
                "graph_path": str(raw.get("graph_path") or ""),
            })
            current["variant_ids"] = sorted(set(current["variant_ids"]) | set(raw.get("variant_ids") or []))
            current["is_seed"] = current["is_seed"] or bool(raw.get("is_seed"))
            current["edge_count"] = max(current["edge_count"], int(number(raw.get("edge_count"))))
            current["weighted_degree"] = max(current["weighted_degree"], number(raw.get("weighted_degree")))
            current["importance"] = max(current["importance"], number(raw.get("importance")))
            if current["topic_score"] is None and raw.get("topic_score") is not None:
                current["topic_score"] = raw["topic_score"]

        ordered = sorted(memberships.values(), key=lambda value: (
            -number(value["importance"]), -number(value["topic_score"]), value["topic_id"], value["graph_path"]))
        max_score = max((number(value["topic_score"]) for value in ordered), default=0.0)
        connectivity = max((number(value["importance"]) for value in ordered), default=0.0)
        relevance = min(max_score / 4.0, 1.0)
        priority = round(0.5 * connectivity + 0.5 * relevance, 6)
        item["graph_memberships"] = ordered
        item["topic_ids"] = sorted({value["topic_id"] for value in ordered})
        item["variant_ids"] = sorted({variant for value in ordered for variant in value["variant_ids"]})
        item["membership_count"] = len(ordered)
        item["dedup_key"] = item["paper_id"]
        item["parse_once"] = True
        item["primary_topic"] = ordered[0]["topic_id"] if ordered else None
        item["importance"] = {"topic_relevance": round(relevance, 6),
                               "graph_connectivity": round(connectivity, 6),
                               "digest_priority": priority}
        item["digest_status"] = "pending"
        queue.append(item)
    return sorted(queue, key=lambda value: (-value["importance"]["digest_priority"], value["paper_id"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path("docs/generated/digest-topic-graphs/three-ai-v2/paper_graph_index.jsonl"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or args.index.with_name("digest_graph_queue.jsonl")
    queue = build_queue(read_jsonl(args.index))
    dedup_keys = [item["dedup_key"] for item in queue]
    if len(dedup_keys) != len(set(dedup_keys)):
        raise SystemExit("duplicate dedup_key in generated queue")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in queue), encoding="utf-8")
    report = {
        "schema_version": "digest_graph_queue_v1",
        "paper_count": len(queue),
        "unique_dedup_keys": len(dedup_keys),
        "membership_count": sum(item["membership_count"] for item in queue),
        "multi_graph_paper_count": sum(item["membership_count"] > 1 for item in queue),
        "queue_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "output": str(output),
    }
    output.with_name("digest_graph_queue_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
