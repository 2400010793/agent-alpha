#!/usr/bin/env python3
"""Stream a v4 JSONL corpus through v5 without rescanning raw OpenAlex Works."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from paper_graph.finance_filter_v5 import (
    FINANCE_AUDIT_VERSION, RESEARCH_VALUE_VERSION, SELECTION_VERSION,
)
from paper_graph.gate2_audit import reaudit_row


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    count = 0
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            count += 1
    temporary.replace(path)
    return count


def _read(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or not row.get("openalex_id"):
                raise ValueError(f"invalid candidate: {path}:{line_number}")
            yield row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-files", type=int)
    args = parser.parse_args()
    paths = sorted(args.input_root.glob("updated_date=*/*.candidates.jsonl"))
    if args.max_files is not None:
        paths = paths[:args.max_files]
    if not paths:
        raise SystemExit(f"no candidate JSONL files under {args.input_root}")

    checkpoint_path = args.output_root / "stream_checkpoints_v1.json"
    config = {
        "selection_version": SELECTION_VERSION,
        "finance_audit_version": FINANCE_AUDIT_VERSION,
        "research_value_version": RESEARCH_VALUE_VERSION,
    }
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {}
    if checkpoint.get("schema_version") != "openalex_v5_stream_checkpoints_v1" or checkpoint.get("config") != config:
        checkpoint = {
            "schema_version": "openalex_v5_stream_checkpoints_v1",
            "config": config,
            "files": {},
        }
    totals: Counter[str] = Counter()
    for path in paths:
        relative = path.relative_to(args.input_root)
        fingerprint = {"bytes": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}
        key = relative.as_posix()
        previous = checkpoint["files"].get(key)
        output = args.output_root / "retained" / relative
        ai_output = args.output_root / "ai_review" / relative
        if previous and previous.get("fingerprint") == fingerprint and output.exists() and ai_output.exists():
            totals.update(previous["summary"])
            print(json.dumps({"file": key, "checkpoint_reused": True, **previous["summary"]}), flush=True)
            continue

        input_count = 0
        retained: list[dict[str, Any]] = []
        ai_review: list[dict[str, Any]] = []
        status: Counter[str] = Counter()
        priorities: Counter[str] = Counter()
        for source in _read(path):
            input_count += 1
            row = reaudit_row(source, filter_profile="v5")
            if not row["retrieval_retained"]:
                continue
            retained.append(row)
            status[row["finance_status"]] += 1
            if row["finance_status"] == "review":
                priorities[row["finance_review_priority"]] += 1
                if row["finance_review_priority"] == "high":
                    ai_review.append(row)
        _atomic_jsonl(output, retained)
        _atomic_jsonl(ai_output, sorted(
            ai_review, key=lambda row: (-int(row["finance_review_priority_score"]), row["openalex_id"])
        ))
        summary = {
            "input_candidates": input_count,
            "retained_candidates": len(retained),
            "demoted_candidates": input_count - len(retained),
            "accepted": status["accepted"], "review": status["review"],
            "rejected_retained": status["rejected"],
            "review_high": priorities["high"], "review_medium": priorities["medium"],
            "review_low": priorities["low"], "ai_review_count": len(ai_review),
        }
        checkpoint["files"][key] = {"fingerprint": fingerprint, "summary": summary}
        _atomic_json(checkpoint_path, checkpoint)
        totals.update(summary)
        print(json.dumps({"file": key, **summary}), flush=True)

    result = {
        "schema_version": "openalex_v5_stream_summary_v1",
        "filter_profile": "v5", **config, "input_file_count": len(paths), **dict(totals),
    }
    _atomic_json(args.output_root / "summary.json", result)
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
