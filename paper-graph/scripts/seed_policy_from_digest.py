#!/usr/bin/env python3
"""Create an auditable incremental seed policy from a Digest queue.

This is a policy-only step. It does not run OpenAlex, rebuild graphs, or alter
existing graph files. It preserves existing seeds and adds at most enough
completed, high-priority Digest papers to reach five seeds per topic.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def priority(row: dict[str, Any]) -> float:
    return float((row.get("importance") or {}).get("digest_priority") or 0.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=Path("docs/generated/digest-topic-graphs/three-ai-v2/digest_graph_queue.jsonl"))
    parser.add_argument("--status", type=Path, default=Path("docs/generated/digest-topic-graphs/three-ai-v2/digest_processing_status.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("docs/generated/digest-topic-graphs/three-ai-v2/seed_policy.json"))
    parser.add_argument("--max-seeds", type=int, default=5)
    parser.add_argument("--minimum-priority", type=float, default=0.75)
    args = parser.parse_args()
    if not 1 <= args.max_seeds <= 5:
        raise SystemExit("max-seeds must be between 1 and 5")
    queue = {str(row.get("paper_id")): row for row in read_jsonl(args.queue) if row.get("paper_id")}
    statuses = {str(row.get("paper_id")): row for row in read_jsonl(args.status) if row.get("paper_id")}
    topics: dict[str, list[tuple[float, str]]] = {}
    for paper_id, row in queue.items():
        if statuses.get(paper_id, {}).get("status") != "completed":
            continue
        if priority(row) < args.minimum_priority:
            continue
        for topic_id in row.get("topic_ids", []):
            topics.setdefault(str(topic_id), []).append((priority(row), paper_id))
    policy = {
        "schema_version": "digest_incremental_seed_policy_v1",
        "max_seeds_per_topic": args.max_seeds,
        "minimum_digest_priority": args.minimum_priority,
        "allowed_seed_ids_by_topic": {},
        "new_digest_papers_are_not_automatically_seeds": True,
        "graphs_modified": False,
    }
    for topic_id, candidates in sorted(topics.items()):
        candidates.sort(key=lambda item: (-item[0], item[1]))
        policy["allowed_seed_ids_by_topic"][topic_id] = [paper_id for _, paper_id in candidates[:args.max_seeds]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"topics": len(policy["allowed_seed_ids_by_topic"]), "completed_candidates": sum(len(v) for v in policy["allowed_seed_ids_by_topic"].values()), "graphs_modified": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
