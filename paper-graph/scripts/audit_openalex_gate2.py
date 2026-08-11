#!/usr/bin/env python3
"""Re-audit an existing OpenAlex sample and emit deterministic Gate 2 artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_graph.gate2_audit import (
    build_gate2_summary,
    build_stratified_review_sample,
    read_candidate_rows,
    reaudit_row,
    sha256_file,
)
from paper_graph.filter_profiles import FILTER_PROFILES


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def _review_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "openalex_id": row.get("openalex_id"),
        "canonical_paper_id": row.get("canonical_paper_id"),
        "title": row.get("title"),
        "publication_year": row.get("publication_year"),
        "language": row.get("language"),
        "arxiv_id": row.get("arxiv_id"),
        "finance_review_priority": row.get("finance_review_priority"),
        "finance_review_priority_score": row.get("finance_review_priority_score"),
        "finance_audit_reasons": row.get("finance_audit_reasons"),
        "finance_anchors": row.get("finance_anchors"),
        "quant_match": row.get("quant_match"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=180)
    parser.add_argument("--random-seed", type=int, default=20260810)
    parser.add_argument("--accepted-precision-threshold", type=float, default=0.90)
    parser.add_argument(
        "--filter-profile", choices=tuple(FILTER_PROFILES), default="v4",
        help="Recompute matches and audits with a versioned profile.",
    )
    parser.add_argument(
        "--review-mode",
        choices=("manual", "ai", "deterministic"),
        default="manual",
        help="Record the approval policy without rewriting reviewer fields.",
    )
    args = parser.parse_args()

    paths = sorted(args.input_root.glob("updated_date=*/*.candidates.jsonl"))
    if not paths:
        raise SystemExit(f"no candidate JSONL files under {args.input_root}")
    rows = [reaudit_row(row, filter_profile=args.filter_profile) for row in read_candidate_rows(paths)]
    summary = build_gate2_summary(rows)
    sample = build_stratified_review_sample(
        rows, sample_size=args.sample_size, random_seed=args.random_seed
    )
    input_files = [
        {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in paths
    ]
    input_fingerprint = hashlib.sha256(
        "".join(item["sha256"] for item in input_files).encode("ascii")
    ).hexdigest()
    candidates_path = args.output_root / "candidates.jsonl"
    _write_jsonl(candidates_path, rows)
    retained_path = args.output_root / "retained_candidates.jsonl"
    retained = [row for row in rows if row.get("retrieval_retained")]
    _write_jsonl(retained_path, retained)
    accepted_path = args.output_root / "accepted_candidates.jsonl"
    accepted = [row for row in retained if row.get("finance_status") == "accepted"]
    _write_jsonl(accepted_path, accepted)
    reviews = [row for row in retained if row.get("finance_status") == "review"]
    review_sort = lambda row: (
        -int(row.get("finance_review_priority_score") or 0),
        str(row.get("openalex_id") or ""),
    )
    ai_review_path = args.output_root / "ai_review_queue.jsonl"
    ai_review = [_review_projection(row) for row in sorted(reviews, key=review_sort)
                 if row.get("finance_review_priority") == "high"]
    _write_jsonl(ai_review_path, ai_review)
    watchlist_path = args.output_root / "deterministic_watchlist.jsonl"
    watchlist = [_review_projection(row) for row in sorted(reviews, key=review_sort)
                 if row.get("finance_review_priority") == "medium"]
    _write_jsonl(watchlist_path, watchlist)
    gate_status = {
        "manual": "pending_manual_review",
        "ai": "pending_ai_review",
        "deterministic": "deterministic_screen_complete",
    }[args.review_mode]
    notes = {
        "manual": "Populate human_finance_status in review_sample.jsonl, then evaluate precision; this command never approves Gate 3.",
        "ai": "Write versioned AI review fields to a separate artifact; never populate human_finance_status from an LLM.",
        "deterministic": "Deterministic finance and research-value screening completed; proceed only after output reconciliation.",
    }
    manifest = {
        "schema_version": "openalex_gate2_manifest_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_root": str(args.input_root.resolve()),
        "input_files": input_files,
        "input_fingerprint": input_fingerprint,
        "retrieval_count": len(rows),
        "sample_size": len(sample),
        "random_seed": args.random_seed,
        "accepted_precision_threshold": args.accepted_precision_threshold,
        "review_mode": args.review_mode,
        "filter_profile": args.filter_profile,
        "gate_status": gate_status,
        "candidate_output": {
            "path": str(candidates_path.resolve()),
            "bytes": candidates_path.stat().st_size,
            "sha256": sha256_file(candidates_path),
            "row_count": len(rows),
        },
        "retained_output": {
            "path": str(retained_path.resolve()), "sha256": sha256_file(retained_path),
            "row_count": len(retained),
        },
        "accepted_output": {
            "path": str(accepted_path.resolve()), "sha256": sha256_file(accepted_path),
            "row_count": len(accepted),
        },
        "ai_review_queue": {
            "path": str(ai_review_path.resolve()), "sha256": sha256_file(ai_review_path),
            "row_count": len(ai_review), "policy": "v5_high_priority_only",
        },
        "deterministic_watchlist": {
            "path": str(watchlist_path.resolve()), "sha256": sha256_file(watchlist_path),
            "row_count": len(watchlist),
        },
        "note": notes[args.review_mode],
    }
    _write_json(args.output_root / "summary.json", summary)
    _write_jsonl(args.output_root / "review_sample.jsonl", sample)
    _write_json(args.output_root / "manifest.json", manifest)
    print(json.dumps({"status": "ok", **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
