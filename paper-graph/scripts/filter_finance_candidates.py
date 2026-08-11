#!/usr/bin/env python3
"""Audit and filter OpenAlex candidates for finance-domain relevance.

This is a conservative, offline pre-filter. It keeps the source candidate file
unchanged and writes accepted/rejected rows plus an audit summary. Titles are
used because the compact candidate JSONL does not contain abstracts/concepts.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

FINANCE_TERMS = {
    "asset", "arbitrage", "bank", "bond", "capital", "commodity", "credit",
    "crypto", "cryptocurrency", "defi", "derivative", "dividend", "equity",
    "exchange", "financial", "finance", "forex", "futures", "hedging", "investor",
    "liquidity", "loan", "market", "microstructure", "option", "portfolio",
    "pricing", "return", "risk", "stock", "trading", "volatility", "yield",
    "orderbook", "order-book", "order", "bid", "ask", "spread", "execution",
    "alpha", "factor", "premium", "sentiment", "price", "fund", "wealth",
}
STRONG_FINANCE_PATTERNS = [
    r"financial market", r"stock market", r"asset pricing", r"portfolio",
    r"limit order book", r"order flow", r"market microstructure", r"price impact",
    r"option pricing", r"financial trading", r"cryptocurrency market",
    r"return predict", r"volatility forecast", r"risk premia?", r"equity premium",
]
NONFINANCE_TERMS = {
    "battery", "batteries", "catalyst", "cancer", "clinical", "disease", "medical",
    "medicine", "protein", "gene", "genome", "patient", "cell", "lithium",
    "electrocatalyst", "molecular", "plant", "drug", "stroke", "mortality",
    "obesity", "acoustics", "speech", "wireless", "antenna", "image segmentation",
    "skin cancer", "protein structure", "medical image", "maternal", "healthcare",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9-]+", " ", text.lower())).strip()


def score(row: dict[str, Any], topic_keywords: list[str]) -> dict[str, Any]:
    title = normalize(str(row.get("title") or ""))
    topic_hits = [keyword for keyword in topic_keywords if normalize(keyword) in title]
    finance_hits = sorted({term for term in FINANCE_TERMS if re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", title)})
    nonfinance_hits = sorted({term for term in NONFINANCE_TERMS if term in title})
    strong_hits = [pattern for pattern in STRONG_FINANCE_PATTERNS if re.search(pattern, title)]
    # Exact topic phrases and strong finance phrases carry more weight than
    # generic words such as factor, risk, impact, market, or model.
    value = 2 * len(strong_hits) + 2 * len(topic_hits) + len(finance_hits)
    value -= 4 * len(nonfinance_hits)
    if nonfinance_hits and not strong_hits and not (set(finance_hits) & {"financial", "finance", "stock", "asset", "portfolio", "trading", "market", "pricing", "return", "liquidity", "order", "volatility", "option", "derivative", "bond", "equity", "credit"}):
        value -= 3
    status = "accepted" if value >= 3 and (strong_hits or topic_hits or len(finance_hits) >= 2) and not (len(nonfinance_hits) >= 2 and not strong_hits) else "review"
    if value <= 0 or len(nonfinance_hits) >= 2 and not strong_hits:
        status = "rejected"
    return {"finance_score": value, "topic_hits": topic_hits, "finance_hits": finance_hits,
            "nonfinance_hits": nonfinance_hits, "strong_finance_hits": strong_hits, "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    taxonomy = json.loads(args.taxonomy.read_text(encoding="utf-8"))
    keywords = {str(child["id"]): list(child.get("keywords") or [])
                for first in taxonomy.get("first_levels", []) for child in first.get("children", [])}
    rows = read_jsonl(args.input)
    audited = []
    for row in rows:
        topic_results = {topic: score(row, keywords.get(topic, [])) for topic in row.get("topic_ids", [])}
        result = dict(row)
        result["finance_audit"] = topic_results
        result["finance_status"] = "accepted" if any(x["status"] == "accepted" for x in topic_results.values()) else (
            "review" if any(x["status"] == "review" for x in topic_results.values()) else "rejected")
        audited.append(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    accepted = args.output.with_name(args.output.stem + "-accepted.jsonl")
    rejected = args.output.with_name(args.output.stem + "-rejected.jsonl")
    review = args.output.with_name(args.output.stem + "-review.jsonl")
    for path, status in [(accepted, "accepted"), (rejected, "rejected"), (review, "review")]:
        with path.open("w", encoding="utf-8") as handle:
            for row in audited:
                if row["finance_status"] == status:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    counts = Counter(row["finance_status"] for row in audited)
    topic_counts = defaultdict(Counter)
    for row in audited:
        for topic, result in row["finance_audit"].items():
            topic_counts[topic][result["status"]] += 1
    summary = {"input_count": len(rows), "status_counts": dict(counts),
               "topic_counts": {topic: dict(value) for topic, value in sorted(topic_counts.items())},
               "accepted": str(accepted), "review": str(review), "rejected": str(rejected),
               "note": "Title-only conservative audit; review rows require abstract/concept verification before replacement."}
    args.output.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
