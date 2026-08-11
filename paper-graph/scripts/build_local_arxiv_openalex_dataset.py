#!/usr/bin/env python3
"""Build a local post-2016 arXiv→OpenAlex dataset without per-paper API calls.

The input may contain records produced by the existing 85-keyword crawler and
its OpenAlex fallback. Records are deduplicated by canonical arXiv ID, merged,
and assigned a transparent finance relevance score from categories, title,
abstract, and OpenAlex metadata available in the input.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ARXIV_ID = re.compile(r"(?:arxiv:|arxiv\.org/(?:abs|pdf)/)?([0-9]{4}\.\d{4,5})(?:v\d+)?$", re.I)
STRONG = {
    "finance", "financial", "financial market", "financial markets", "asset pricing",
    "asset price", "portfolio", "trading", "trader", "stock market", "stock price",
    "option pricing", "derivative pricing", "volatility", "liquidity", "market microstructure",
    "order book", "price impact", "risk management", "credit risk", "foreign exchange",
    "forex", "cryptocurrency", "bitcoin", "blockchain", "yield curve", "bond market",
    "optimal execution", "algorithmic trading", "econometrics", "financial economics",
}
WEAK = {"market", "economic", "economics", "risk", "return", "exchange", "pricing", "bank"}
NEGATIVE = {"particle", "quantum", "galaxy", "cosmology", "medical", "protein", "image", "speech", "robotics"}


def canonical(value: Any) -> str | None:
    match = ARXIV_ID.search(str(value or "").strip())
    return match.group(1) if match else None


def arxiv_year(ident: str) -> int | None:
    prefix = ident.split(".", 1)[0]
    if len(prefix) != 4 or not prefix.isdigit():
        return None
    return 2000 + int(prefix[:2])


def text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def read_records(paths: list[Path]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ident = canonical(row.get("arxiv_id") or row.get("url"))
            if not ident:
                continue
            row = dict(row)
            row["arxiv_id"] = ident
            current = merged.get(ident, {})
            current.update({k: v for k, v in row.items() if v not in (None, "", [])})
            merged[ident] = current
    return merged


def score(row: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    title = text(row.get("title"))
    abstract = text(row.get("summary") or row.get("abstract"))
    categories = " ".join(row.get("categories") or []).casefold()
    metadata = text(row.get("source")) + " " + text(row.get("source_name"))
    haystack = " ".join((title, abstract, categories, metadata))
    reasons = sorted(term for term in STRONG if term in haystack)
    weak = sorted(term for term in WEAK if term in haystack)
    negatives = sorted(term for term in NEGATIVE if term in title)
    value = min(100, len(reasons) * 12 + min(20, len(weak) * 3))
    if categories.startswith("q-fin.") or "econ." in categories:
        value += 25
    if negatives and not reasons:
        value -= 30
    return max(0, min(100, value)), reasons, negatives


def main() -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--input", action="append", type=Path, default=[])
    parser.add_argument("--primary-input", type=Path, default=None)
    parser.add_argument("--all-output", type=Path, default=root / "docs/generated/arxiv-openalex-2016plus-local.jsonl")
    parser.add_argument("--finance-output", type=Path, default=root / "docs/generated/arxiv-finance-openalex-2016plus-local.jsonl")
    parser.add_argument("--review-output", type=Path, default=root / "docs/generated/arxiv-finance-screening-review-2016plus.jsonl")
    parser.add_argument("--min-year", type=int, default=2016)
    parser.add_argument("--threshold", type=int, default=25)
    args = parser.parse_args()
    default_inputs = [
        root.parent / "my-paper-digest-new2/data/arxiv_85keyword_openalex_links_10y.jsonl",
        root.parent / "my-paper-digest-new2/data/arxiv_85keyword_links_10y.jsonl",
        root / "docs/generated/arxiv-finance-201601-probe-raw.jsonl",
    ]
    records = read_records(args.input or default_inputs)
    if args.primary_input:
        primary = read_records([args.primary_input])
        records = {ident: records.get(ident, row) for ident, row in primary.items()}
    all_rows: list[dict[str, Any]] = []
    finance_rows: list[dict[str, Any]] = []
    uncertain_rows: list[dict[str, Any]] = []
    for ident, row in sorted(records.items()):
        year_text = str(row.get("published") or row.get("year") or "")[:4]
        if not year_text.isdigit():
            inferred = arxiv_year(ident)
            year_text = str(inferred) if inferred is not None else ""
        if not year_text.isdigit() or int(year_text) < args.min_year:
            continue
        value, reasons, negatives = score(row)
        row = {**row, "arxiv_id": ident, "inferred_year": int(year_text), "finance_relevance_score": value,
               "finance_relevance_terms": reasons, "negative_title_terms": negatives,
             "finance_relevance": value >= args.threshold,
             "screening_decision": "finance" if value >= args.threshold else ("review" if value >= 10 else "not_finance")}
        all_rows.append(row)
        if value >= args.threshold and row.get("openalex_id"):
            finance_rows.append(row)
        if 10 <= value < args.threshold:
            uncertain_rows.append(row)
    for path, rows in ((args.all_output, all_rows), (args.finance_output, finance_rows),
                       (args.review_output, uncertain_rows)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(json.dumps({"input_unique": len(records), "post_2016": len(all_rows),
                      "finance_with_openalex": len(finance_rows),
                      "finance_all": sum(r["screening_decision"] == "finance" for r in all_rows),
                      "needs_manual_review": len(uncertain_rows),
                      "not_finance": sum(r["screening_decision"] == "not_finance" for r in all_rows),
                      "score_threshold": args.threshold,
                      "years": dict(Counter(str(r.get('published',''))[:4] for r in all_rows)),
                      "all_output": str(args.all_output), "finance_output": str(args.finance_output)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
