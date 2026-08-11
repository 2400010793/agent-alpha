#!/usr/bin/env python3
"""Deduplicate three-stage paper analysis archives and write an audit report.

The project has several historical batch archives.  A paper is identified by
normalized arXiv id (version suffixes are ignored), not by the file it came
from.  Duplicate rows are merged field-by-field, keeping the non-empty/richer
value instead of silently selecting one batch.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUTS = [
    "data/analysis_archive.jsonl",
    "data/arxiv_tex_three_ai_analysis.jsonl",
    "data/opinion_analysis_archive.jsonl",
    "data/opinion_batch_analysis_20260723.jsonl",
    "data/opinion_batch_analysis_gpt54mini_20260724.jsonl",
    "data/opinion_batch_analysis_gpt54mini_20260724_probe.jsonl",
    "data/opinion_batch_analysis_gpt54mini_20260724_retry.jsonl",
    "data/opinion_batch_analysis_gpt54mini_20260724_retry2.jsonl",
    "data/opinion_batch_analysis_gpt54mini_20260724_topic_enriched.jsonl",
]


def paper_id(row: dict[str, Any]) -> str:
    value = str(row.get("arxiv_id") or row.get("id") or row.get("article_id") or row.get("paper_id") or "")
    value = value.strip().lower().removeprefix("arxiv:")
    return re.sub(r"v\d+$", "", value)


def has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def richness(row: dict[str, Any]) -> tuple[int, int]:
    stage_keys = (
        "llm_reading_note", "reading_note", "reading_note_v1",
        "paper_hf_factors", "article_opinions", "opinion_analysis",
        "llm_faithfulness_audit", "faithfulness_audit", "llm_opinion_faithfulness_audit",
    )
    return (sum(has_value(row.get(key)) for key in stage_keys), len(json.dumps(row, ensure_ascii=False)))


def merge_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for row in sorted(rows, key=richness):
        for key, value in row.items():
            if not has_value(value):
                continue
            if key not in merged or not has_value(merged[key]) or (isinstance(value, dict) and isinstance(merged[key], dict) and len(value) > len(merged[key])):
                merged[key] = value
    merged["arxiv_id"] = paper_id(merged)
    merged["dedup_source_count"] = len(rows)
    merged["dedup_sources"] = sorted({str(row.get("_source_file", "")) for row in rows if row.get("_source_file")})
    return merged


def stage_flags(row: dict[str, Any]) -> dict[str, bool]:
    note = row.get("llm_reading_note") or row.get("reading_note") or row.get("reading_note_v1")
    # The active opinion pipeline uses article_opinions; the legacy HF branch
    # uses paper_hf_factors. Both are valid stage-2 outputs in historical data.
    stage2 = row.get("paper_hf_factors") or row.get("article_opinions") or row.get("opinion_analysis")
    audit = row.get("llm_faithfulness_audit") or row.get("faithfulness_audit") or row.get("llm_opinion_faithfulness_audit")
    return {"reading": has_value(note), "generation": has_value(stage2), "audit": has_value(audit)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "three_ai_deduplicated_archive.jsonl")
    parser.add_argument("--report", type=Path, default=ROOT / "reports" / "three_ai_dedup_report.json")
    args = parser.parse_args()
    inputs = [path if path.is_absolute() else ROOT / path for path in (args.input or [Path(item) for item in DEFAULT_INPUTS])]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    raw_rows = 0
    invalid_rows = 0
    for path in inputs:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                invalid_rows += 1
                continue
            identifier = paper_id(row)
            if not identifier:
                continue
            raw_rows += 1
            row = dict(row)
            row["_source_file"] = str(path.relative_to(ROOT))
            grouped[identifier].append(row)

    deduped = [merge_rows(rows) for _, rows in sorted(grouped.items())]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in deduped), encoding="utf-8")
    stage_counts = {stage: sum(stage_flags(row)[stage] for row in deduped) for stage in ("reading", "generation", "audit")}
    complete = [row for row in deduped if all(stage_flags(row).values())]
    report = {
        "schema_version": "three_ai_dedup_audit_v1",
        "input_files": [str(path.relative_to(ROOT)) for path in inputs if path.exists()],
        "raw_rows": raw_rows,
        "invalid_rows": invalid_rows,
        "unique_papers": len(deduped),
        "duplicate_rows_removed": raw_rows - len(deduped),
        "duplicate_paper_groups": sum(len(rows) > 1 for rows in grouped.values()),
        "stage_presence_after_dedup": stage_counts,
        "complete_three_stage_papers": len(complete),
        "complete_three_stage_ids": [row["arxiv_id"] for row in complete],
        "duplicate_groups": {identifier: sorted({row["_source_file"] for row in rows}) for identifier, rows in grouped.items() if len(rows) > 1},
        "outputs": {"archive": str(args.output.relative_to(ROOT)), "report": str(args.report.relative_to(ROOT))},
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("raw_rows", "unique_papers", "duplicate_rows_removed", "complete_three_stage_papers")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())