#!/usr/bin/env python3
"""Create a safe Paper Digest result registry from the de-duplicated queue.

This script does not run Paper Digest and does not build or modify graph files.
It only records processing status and creates lightweight topic views pointing
to one canonical result per paper.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUSES = {"pending", "processing", "completed", "failed", "retry"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def load_queue(path: Path) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    keys = [str(row.get("dedup_key") or row.get("paper_id") or "") for row in rows]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise ValueError("queue contains missing or duplicate dedup_key values")
    return rows


def build_registry(queue: list[dict[str, Any]], existing: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    previous = {str(row.get("dedup_key") or row.get("paper_id")): row for row in existing or []}
    registry: list[dict[str, Any]] = []
    for item in queue:
        key = str(item.get("dedup_key") or item.get("paper_id"))
        old = previous.get(key, {})
        status = str(old.get("status") or item.get("digest_status") or "pending")
        if status not in STATUSES:
            status = "pending"
        registry.append({
            "paper_id": item.get("paper_id"),
            "dedup_key": key,
            "topic_ids": item.get("topic_ids", []),
            "variant_ids": item.get("variant_ids", []),
            "membership_count": item.get("membership_count", 0),
            "graph_version": "three-ai-v2",
            "status": status,
            "attempt": int(old.get("attempt") or 0),
            "result_path": old.get("result_path"),
            "error": old.get("error"),
            "updated_at": old.get("updated_at") or now(),
        })
    return registry


def validate_result(result: dict[str, Any], item: dict[str, Any]) -> None:
    result_key = str(result.get("dedup_key") or result.get("paper_id") or "")
    if result_key != item["dedup_key"]:
        raise ValueError(f"result identity mismatch for {item['paper_id']}: {result_key}")


def sync_results(queue: list[dict[str, Any]], registry: list[dict[str, Any]], results_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_key = {row["dedup_key"]: row for row in registry}
    result_index: list[dict[str, Any]] = []
    topic_views: list[dict[str, Any]] = []
    for item in queue:
        key = str(item.get("dedup_key") or item.get("paper_id"))
        result_path = results_dir / f"{str(item['paper_id']).replace(':', '_')}.json"
        state = by_key[key]
        if not result_path.exists():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        validate_result(result, item)
        state.update({"status": "completed", "result_path": str(result_path), "error": None, "updated_at": now()})
        result_index.append({
            "paper_id": item["paper_id"],
            "dedup_key": key,
            "result_path": str(result_path),
            "topic_ids": item.get("topic_ids", []),
            "variant_ids": item.get("variant_ids", []),
            "membership_count": item.get("membership_count", 0),
        })
        for membership in item.get("graph_memberships", []):
            topic_views.append({
                "paper_id": item["paper_id"],
                "dedup_key": key,
                "result_path": str(result_path),
                "topic_id": membership.get("topic_id"),
                "variant_ids": membership.get("variant_ids", []),
                "importance": membership.get("importance", 0.0),
                "digest_priority": item.get("importance", {}).get("digest_priority", 0.0),
            })
    return result_index, topic_views


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=Path("docs/generated/digest-topic-graphs/three-ai-v2/digest_graph_queue.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--results-dir", type=Path, default=None)
    args = parser.parse_args()
    output_dir = args.output_dir or args.queue.parent
    results_dir = args.results_dir or output_dir / "digest-results"
    queue = load_queue(args.queue)
    status_path = output_dir / "digest_processing_status.jsonl"
    registry = build_registry(queue, read_jsonl(status_path))
    result_index, topic_views = sync_results(queue, registry, results_dir)
    write_jsonl(status_path, registry)
    write_jsonl(output_dir / "digest_result_index.jsonl", result_index)
    write_jsonl(output_dir / "digest_topic_views.jsonl", topic_views)
    summary = {
        "schema_version": "digest_result_registry_v1",
        "queue_count": len(queue),
        "completed_count": sum(row["status"] == "completed" for row in registry),
        "pending_count": sum(row["status"] == "pending" for row in registry),
        "failed_count": sum(row["status"] == "failed" for row in registry),
        "result_count": len(result_index),
        "topic_view_count": len(topic_views),
        "deduplication": "one_result_per_dedup_key",
        "graphs_modified": False,
    }
    (output_dir / "digest_result_registry_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
