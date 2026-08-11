#!/usr/bin/env python3
"""Create a resumable OpenAlex matching queue from screened arXiv records."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--screened", type=Path, default=root / "docs/generated/arxiv-factor-8732-screened.jsonl")
    parser.add_argument("--output", type=Path, default=root / "docs/generated/arxiv-factor-8732-openalex-queue.jsonl")
    parser.add_argument("--min-score", type=int, default=25)
    parser.add_argument("--all-screened", action="store_true",
                        help="include every screened record, regardless of finance decision or score")
    args = parser.parse_args()
    rows: list[dict[str, Any]] = []
    for line in args.screened.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not args.all_screened and (row.get("screening_decision") != "finance" or
                                      int(row.get("finance_relevance_score", 0)) < args.min_score):
            continue
        match = row.get("openalex_id")
        row["openalex_match_status"] = "already_matched" if match else "pending"
        if not match or args.all_screened:
            rows.append({"arxiv_id": row.get("arxiv_id"), "title": row.get("title"),
                         "summary": row.get("summary"), "inferred_year": row.get("inferred_year"),
                         "finance_relevance_score": row.get("finance_relevance_score"),
                         "finance_relevance_terms": row.get("finance_relevance_terms"),
                         "screening_decision": row.get("screening_decision"),
                         "existing_openalex_id": match,
                         "status": "pending"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(json.dumps({"pending": len(rows), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())