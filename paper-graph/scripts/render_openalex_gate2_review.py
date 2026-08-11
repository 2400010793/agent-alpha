#!/usr/bin/env python3
"""Render the Gate 2 JSONL review sample as readable Markdown and CSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


FIELDS = (
    "number",
    "openalex_id",
    "arxiv_id",
    "publication_year",
    "automatic_finance_status",
    "title",
    "matched_canonical_terms",
    "matched_fields",
    "automatic_reasons",
    "human_finance_status",
    "human_review_reason",
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"review row must be an object: {path}:{line_number}")
            rows.append(value)
    return rows


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return "" if value is None else str(value)


def _flat_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "number": str(index),
            **{field: _text(row.get(field)) for field in FIELDS if field != "number"},
        }
        for index, row in enumerate(rows, start=1)
    ]


def _atomic_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _escape_markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _atomic_markdown(path: Path, rows: list[dict[str, str]]) -> None:
    counts = Counter(row["automatic_finance_status"] for row in rows)
    lines = [
        "# OpenAlex Gate 2 review sample",
        "",
        f"Total: {len(rows)}; accepted: {counts['accepted']}; review: {counts['review']}; rejected: {counts['rejected']}.",
        "",
        "Fill `human_finance_status` with `accepted`, `review`, or `rejected`; do not change the automatic columns.",
        "",
        "| # | OpenAlex | arXiv | Year | Auto | Title | Terms | Fields | Auto reasons | Human status | Human reason |",
        "|---:|---|---|---:|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        values = (
            row["number"],
            row["openalex_id"],
            row["arxiv_id"],
            row["publication_year"],
            row["automatic_finance_status"],
            row["title"],
            row["matched_canonical_terms"],
            row["matched_fields"],
            row["automatic_reasons"],
            row["human_finance_status"],
            row["human_review_reason"],
        )
        lines.append("| " + " | ".join(_escape_markdown(value) for value in values) + " |")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-sample", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    rows = _flat_rows(_read_jsonl(args.review_sample))
    _atomic_markdown(args.markdown, rows)
    _atomic_csv(args.csv, rows)
    counts = Counter(row["automatic_finance_status"] for row in rows)
    print(json.dumps({
        "status": "ok",
        "row_count": len(rows),
        "automatic_finance_status": dict(sorted(counts.items())),
        "markdown": str(args.markdown.resolve()),
        "csv": str(args.csv.resolve()),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())