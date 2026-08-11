#!/usr/bin/env python3
"""Build deduplicated arXiv candidate pools for the ten HF mechanism categories."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from src.io.feed import parse_rss_or_atom
from src.io.config import load_config

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data" / "arxiv_mechanism_category_candidates.jsonl"
DEFAULT_STATUS = ROOT / "data" / "arxiv_mechanism_category_candidates.status.json"
DEFAULT_SOURCE_CONFIG = ROOT / "config" / "sources.yaml"

# These are retrieval labels, not final classifications. Reading/evidence later
# still decides the single hf_mechanism_category or none.
# ``strong`` terms identify the mechanism directly. ``support`` terms are
# intentionally broader and are accepted only when at least two occur. This
# prevents a paper containing the generic word "liquidity" from being assigned
# to spread_liquidity by itself.
CATEGORY_TERMS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "order_book_pressure": {"strong": ("order book", "order-book", "limit order book", "quote imbalance", "queue imbalance", "depth imbalance", "book imbalance", "order flow pressure"), "support": ("bid pressure", "ask pressure", "order flow", "market depth", "limit orders", "price formation")},
    "depute_imbalance": {"strong": ("order imbalance", "order-flow imbalance", "flow imbalance", "order flow imbalance", "signed order flow", "buy-sell imbalance", "buy sell imbalance", "ofi", "net order flow"), "support": ("directional order flow", "buying pressure", "selling pressure", "trade direction", "signed trades", "order flow toxicity")},
    "trade_impact": {"strong": ("price impact", "market impact", "trade impact", "order impact", "temporary impact", "permanent impact", "kyle lambda", "metaorder", "transient price impact"), "support": ("execution cost", "price response", "large trade", "market impact model", "optimal execution", "optimal liquidation", "order flow")},
    "price_volume_divergence": {"strong": ("price-volume", "price volume", "volume-return", "return-volume", "price volume lead-lag", "volume-price dynamics", "volume-return relation"), "support": ("volume shock", "volume-induced", "price-volume reversal", "trading volume", "trading volume movement", "volume movement", "volume predictability", "return predictability")},
    "spread_liquidity": {"strong": ("bid-ask spread", "bid ask spread", "quoted spread", "effective spread", "liquidity provision", "market depth", "liquidity imbalance", "liquidity risk", "adverse selection"), "support": ("liquidity", "transaction cost", "market liquidity", "depth", "trading cost", "liquidity providers", "liquidity costs")},
    "short_reversal": {"strong": ("short-term reversal", "intraday reversal", "return reversal", "price reversal", "reversal effect", "contrarian effect", "contrarian effects"), "support": ("contrarian", "contrarian trading", "mean reversion", "short horizon", "reversal strategy", "reversal profitability")},
    "short_momentum": {"strong": ("short-term momentum", "intraday momentum", "return continuation", "price continuation", "momentum effect", "time-series momentum", "cross-sectional momentum"), "support": ("trend continuation", "momentum strategy", "momentum strategies", "short horizon", "return predictability")},
    "volatility_burst": {"strong": ("volatility burst", "volatility jump", "volatility shock", "volatility spike", "jump intensity"), "support": ("realized volatility", "volatility clustering", "intraday volatility", "volatility dynamics")},
    "book_shape": {"strong": ("order book shape", "limit order book shape", "depth profile", "depth curve", "book slope", "order book slope", "book convexity", "order book geometry", "depth distribution"), "support": ("depth across levels", "depth imbalance", "liquidity profile", "order book levels", "price levels", "book shape")},
    "trading_rhythm": {"strong": ("intraday seasonality", "intraday periodicity", "time-of-day effect", "time-of-day pattern", "trading periodicity", "trading rhythm", "hawkes process"), "support": ("volume seasonality", "return seasonality", "diurnal pattern", "intraday pattern", "seasonal trading", "time-dependent background rate", "event intensity", "trade arrival")},
}
CATEGORY_QUERIES: Dict[str, tuple[str, ...]] = {
    category: terms["strong"] + terms["support"] for category, terms in CATEGORY_TERMS.items()
}
# Restrict retrieval to quantitative-finance and machine-learning arXiv
# categories.  ``cs.LG`` covers machine learning broadly, while ``stat.ML``
# covers the statistics/ML side.  Final mechanism classification still happens
# later from the evidence package; these are only source-level filters.
ARXIV_CATEGORIES = ("q-fin.*", "cs.LG", "stat.ML")


def source_defaults(config_path: Path) -> Dict[str, Any]:
    """Read shared crawler defaults without using broad terms as categories."""
    if not config_path.exists():
        return {}
    defaults, _ = load_config(config_path)
    return defaults


def month_range(start: str, end: str) -> Iterable[str]:
    year, month = int(start[:4]), int(start[4:])
    end_year, end_month = int(end[:4]), int(end[4:])
    while (year, month) <= (end_year, end_month):
        yield f"{year:04d}{month:02d}"
        month += 1
        if month == 13:
            year, month = year + 1, 1


def month_bounds(month: str) -> tuple[str, str]:
    year, number = int(month[:4]), int(month[4:])
    if number == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, number + 1
    return f"{year:04d}{number:02d}010000", f"{next_year:04d}{next_month:02d}010000"


def default_start() -> str:
    now = datetime.now(timezone.utc)
    index = now.year * 12 + now.month - 24
    year, month = divmod(index, 12)
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}{month:02d}"


def arxiv_id(url: str) -> str:
    identifier = url.rstrip("/").rsplit("/", 1)[-1]
    if "v" in identifier and identifier.rsplit("v", 1)[-1].isdigit():
        identifier = identifier.rsplit("v", 1)[0]
    return identifier


def query_for(terms: tuple[str, ...], month: str) -> str:
    start, end = month_bounds(month)
    text = " OR ".join(f'(ti:"{term}" OR abs:"{term}")' for term in terms)
    cats = " OR ".join(f"cat:{category}" for category in ARXIV_CATEGORIES)
    return f"({text}) AND ({cats}) AND submittedDate:[{start} TO {end}]"


def match_terms(entry: Dict[str, str], category: str) -> Dict[str, List[str]]:
    """Return only terms actually present in title/abstract text."""
    title = str(entry.get("title") or "").lower()
    abstract = str(entry.get("summary") or entry.get("abstract") or "").lower()
    terms = CATEGORY_TERMS[category]
    def contains(text: str, term: str) -> bool:
        # Avoid substring false positives such as ``ofi`` inside ``portfolio``.
        pattern = rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])"
        return re.search(pattern, text) is not None

    return {
        "title_strong": [term for term in terms["strong"] if contains(title, term)],
        "abstract_strong": [term for term in terms["strong"] if contains(abstract, term)],
        "title_support": [term for term in terms["support"] if contains(title, term)],
        "abstract_support": [term for term in terms["support"] if contains(abstract, term)],
    }


def is_relevant_match(matches: Dict[str, List[str]]) -> bool:
    strong = len(matches["title_strong"]) + len(matches["abstract_strong"])
    support = len(matches["title_support"]) + len(matches["abstract_support"])
    return strong >= 1 or support >= 2


def fetch_category(category: str, month: str, max_items: int, timeout_sec: int, user_agent: str) -> List[Dict[str, str]]:
    params = urllib.parse.urlencode({
        "search_query": query_for(CATEGORY_QUERIES[category], month),
        "start": 0,
        "max_results": max_items,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    request = urllib.request.Request(
        f"https://export.arxiv.org/api/query?{params}",
        headers={"User-Agent": user_agent},
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        entries = parse_rss_or_atom(response.read())
    filtered: List[Dict[str, str]] = []
    for entry in entries:
        matches = match_terms(entry, category)
        if is_relevant_match(matches):
            entry["keyword_matches"] = matches
            filtered.append(entry)
    return filtered


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_rows(path: Path) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("arxiv_id"):
            rows[str(row["arxiv_id"])] = row
    return rows


def write_rows(path: Path, rows: Dict[str, Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(rows[key], ensure_ascii=False, sort_keys=True) + "\n" for key in sorted(rows)), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--source-config", type=Path, default=DEFAULT_SOURCE_CONFIG)
    parser.add_argument("--start-month", default=default_start())
    parser.add_argument("--end-month", default=datetime.now(timezone.utc).strftime("%Y%m"))
    parser.add_argument("--max-items", type=int, default=100)
    parser.add_argument("--delay-sec", type=float, default=5.0)
    parser.add_argument("--timeout-sec", type=int, default=90)
    parser.add_argument("--category", choices=sorted(CATEGORY_QUERIES), action="append")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    defaults = source_defaults(args.source_config)
    user_agent = str(defaults.get("user_agent") or "my-paper-digest-new2-category-crawler/1.0")
    categories = args.category or list(CATEGORY_QUERIES)
    tasks = [(category, month) for category in categories for month in month_range(args.start_month, args.end_month)]
    status = load_json(args.status, {"completed": [], "errors": []})
    completed = set(status.get("completed") or [])
    errors = list(status.get("errors") or [])
    rows = load_rows(args.output)
    if args.dry_run:
        print(json.dumps({"categories": categories, "tasks": len(tasks), "start_month": args.start_month, "end_month": args.end_month, "output": str(args.output)}, ensure_ascii=False))
        return 0
    for category, month in tasks:
        task = f"{category}:{month}"
        if task in completed:
            continue
        try:
            entries = fetch_category(category, month, args.max_items, args.timeout_sec, user_agent)
            added = 0
            for entry in entries:
                identifier = arxiv_id(str(entry.get("url") or ""))
                if not identifier:
                    continue
                row = rows.setdefault(identifier, {
                    "arxiv_id": identifier,
                    "title": str(entry.get("title") or "").strip(),
                    "url": f"https://arxiv.org/abs/{identifier}",
                    "summary": str(entry.get("summary") or "").strip(),
                    "published": str(entry.get("published") or "").strip(),
                    "source_id": "arxiv_api_category",
                    "source_name": "arXiv mechanism category candidate",
                    "source_config": str(args.source_config),
                    "retrieval_user_agent": user_agent,
                    "candidate_categories": [],
                    "matched_query_terms": {},
                })
                candidate_categories = set(row.get("candidate_categories") or [])
                candidate_categories.add(category)
                row["candidate_categories"] = sorted(candidate_categories)
                matched = dict(row.get("matched_query_terms") or {})
                matched[category] = entry.get("keyword_matches") or {}
                row["matched_query_terms"] = matched
                added += 1
            completed.add(task)
            print(json.dumps({"status": "ok", "task": task, "entries": len(entries), "added_or_updated": added, "rows": len(rows)}, ensure_ascii=False), flush=True)
        except Exception as exc:
            error = {"task": task, "category": category, "month": month, "error_type": type(exc).__name__, "error": str(exc), "ts": datetime.now(timezone.utc).isoformat()}
            errors.append(error)
            print(json.dumps({"status": "error", **error}, ensure_ascii=False), file=sys.stderr, flush=True)
        status.update({"completed": sorted(completed), "errors": errors, "rows": len(rows), "source_config": str(args.source_config), "arxiv_categories": list(ARXIV_CATEGORIES), "updated_at": datetime.now(timezone.utc).isoformat()})
        save(args.status, status)
        write_rows(args.output, rows)
        if args.delay_sec > 0:
            time.sleep(args.delay_sec)
    status.update({"completed": sorted(completed), "errors": errors, "rows": len(rows), "finished_at": datetime.now(timezone.utc).isoformat()})
    save(args.status, status)
    write_rows(args.output, rows)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
