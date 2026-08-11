#!/usr/bin/env python3
"""Collect factor-related arXiv metadata for a configurable historical window."""
from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.io.feed import parse_rss_or_atom
from src.io.http import fetch_url

DEFAULT_OUTPUT = ROOT / "data" / "arxiv_factor_articles_10y.jsonl"
DEFAULT_STATUS = ROOT / "data" / "arxiv_factor_articles_10y.status.json"
CATEGORIES = ("q-fin.*", "stat.ML", "econ.EM")
FACTOR_TERMS = (
    '"asset pricing"', '"factor model"', '"factor investing"',
    '"risk premia"', '"risk premium"', 'factor', 'factors',
    'anomaly', 'anomalies', 'alpha', 'momentum', 'value investing',
    'size effect', 'low volatility', 'carry trade', 'trend following',
    'mean reversion', 'statistical arbitrage', 'portfolio sorting',
)
DEFAULT_KEYWORD_CONFIG = ROOT / "config" / "sources.yaml"
# The main arXiv host is currently more reliable than export.arxiv.org for
# this long, high-recall query. Keep the endpoint configurable at module level
# so a future fallback can be added without changing query construction.
ARXIV_API_URL = "https://arxiv.org/api/query"
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"


def iter_months(start: str, end: str) -> Iterable[str]:
    year, month = int(start[:4]), int(start[4:])
    end_year, end_month = int(end[:4]), int(end[4:])
    while (year, month) <= (end_year, end_month):
        yield f"{year:04d}{month:02d}"
        month += 1
        if month == 13:
            year, month = year + 1, 1


def load_rows(path: Path) -> Dict[str, Dict[str, object]]:
    rows: Dict[str, Dict[str, object]] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("arxiv_id"):
                rows[str(row["arxiv_id"])] = row
    return rows


def save_rows(path: Path, rows: Dict[str, Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(rows[key], ensure_ascii=False) + "\n" for key in sorted(rows)), encoding="utf-8")


def load_status(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"completed": [], "errors": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_search_keywords(path: Path) -> List[str]:
    """Load the configured keyword list without adding a YAML dependency."""
    text = path.read_text(encoding="utf-8")
    in_keywords = False
    keywords: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "keywords:":
            in_keywords = True
            continue
        if in_keywords and line and not line.startswith("-"):
            break
        if in_keywords and line.startswith("-"):
            value = line[1:].strip().strip("'\"")
            if value:
                keywords.append(value)
    return list(dict.fromkeys(keywords))


def _keyword_query(keywords: List[str]) -> str:
    return " OR ".join(f"all:{keyword}" for keyword in keywords)


def _parse_total_results(payload: bytes) -> int | None:
    root = ET.fromstring(payload)
    value = root.findtext(f"{{{OPENSEARCH_NS}}}totalResults")
    return int(value) if value and value.isdigit() else None


def _arxiv_id(entry: Dict[str, str]) -> str:
    return str(entry.get("url") or "").rstrip("/").split("/")[-1].split("v")[0]


def query_page(month: str, *, keywords: List[str], start: int, page_size: int, timeout_sec: int, user_agent: str, retries: int, retry_backoff_sec: float) -> Tuple[List[Dict[str, str]], int | None, int]:
    date_start = f"{month}010000"
    year, month_number = int(month[:4]), int(month[4:])
    last_day = calendar.monthrange(year, month_number)[1]
    category_query = " OR ".join(f"cat:{category}" for category in CATEGORIES)
    term_query = _keyword_query(keywords)
    search_query = f"(({category_query}) AND ({term_query})) AND submittedDate:[{date_start} TO {month}{last_day:02d}2359]"
    params = urllib.parse.urlencode({
        "search_query": search_query,
        "start": start,
        "max_results": page_size,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            payload = fetch_url(f"{ARXIV_API_URL}?{params}", timeout_sec=timeout_sec, user_agent=user_agent, use_proxy=False)
            return parse_rss_or_atom(payload), _parse_total_results(payload), attempt
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(retry_backoff_sec * (2**attempt))
    assert last_error is not None
    raise last_error


def query_month(month: str, *, keywords: List[str], page_size: int, max_pages: int, timeout_sec: int, user_agent: str, retries: int, retry_backoff_sec: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    rows: Dict[str, Dict[str, str]] = {}
    total_results: int | None = None
    retry_count = 0
    for page in range(max_pages):
        entries, page_total, attempts = query_page(month, keywords=keywords, start=page * page_size, page_size=page_size, timeout_sec=timeout_sec, user_agent=user_agent, retries=retries, retry_backoff_sec=retry_backoff_sec)
        total_results = page_total if page_total is not None else total_results
        retry_count += attempts
        for entry in entries:
            article_id = _arxiv_id(entry)
            if article_id:
                rows[article_id] = entry
        if len(entries) < page_size or (total_results is not None and (page + 1) * page_size >= total_results):
            break
    metadata = {"pages": page + 1, "returned": len(rows), "total_results": total_results, "truncated": total_results is not None and len(rows) < total_results and page + 1 >= max_pages, "retry_count": retry_count}
    return list(rows.values()), metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--start-month", default="201607")
    parser.add_argument("--end-month", default=datetime.now(timezone.utc).strftime("%Y%m"))
    parser.add_argument("--max-items", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-backoff-sec", type=float, default=15.0)
    parser.add_argument("--keyword-config", type=Path, default=DEFAULT_KEYWORD_CONFIG)
    parser.add_argument("--temporary-output", action="store_true")
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument("--delay-sec", type=float, default=3.5)
    parser.add_argument("--limit-months", type=int, default=0)
    args = parser.parse_args()

    keywords = load_search_keywords(args.keyword_config)
    if not keywords:
        raise SystemExit(f"No keywords found in {args.keyword_config}")
    output = args.output.with_suffix(args.output.suffix + ".tmp") if args.temporary_output else args.output
    status_path = args.status.with_suffix(args.status.suffix + ".tmp") if args.temporary_output else args.status
    rows = load_rows(output)
    status = load_status(status_path)
    completed = set(status.get("completed") or [])
    errors: List[Dict[str, object]] = list(status.get("errors") or [])
    months = [month for month in iter_months(args.start_month, args.end_month) if month not in completed]
    if args.limit_months > 0:
        months = months[: args.limit_months]

    for index, month in enumerate(months, 1):
        try:
            entries, metadata = query_month(month, keywords=keywords, page_size=args.max_items, max_pages=args.max_pages, timeout_sec=args.timeout_sec, user_agent="factor-study-paper-bot/85-keyword-metadata", retries=args.retries, retry_backoff_sec=args.retry_backoff_sec)
            added = 0
            for entry in entries:
                arxiv_id = str(entry.get("url") or "").rstrip("/").split("/")[-1].split("v")[0]
                if not arxiv_id or arxiv_id in rows:
                    continue
                rows[arxiv_id] = {
                    "arxiv_id": arxiv_id,
                    "title": str(entry.get("title") or "").strip(),
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                    "summary": str(entry.get("summary") or "").strip(),
                    "published": str(entry.get("published") or "").strip(),
                    "source_id": "arxiv_keyword_10y",
                    "source_name": "arXiv 85-keyword q-fin/stat.ML/econ.EM",
                    "keyword_query_count": len(keywords),
                }
                added += 1
            completed.add(month)
            status.update({"completed": sorted(completed), "errors": errors, "rows": len(rows), "last_success": month})
            save_rows(output, rows)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"status": "ok", "month": month, "progress": f"{index}/{len(months)}", "entries": len(entries), "added": added, **metadata, "rows": len(rows)}, ensure_ascii=False), flush=True)
        except Exception as exc:
            error = {"month": month, "error_type": type(exc).__name__, "error": str(exc), "ts": datetime.now(timezone.utc).isoformat()}
            errors.append(error)
            status.update({"completed": sorted(completed), "errors": errors, "rows": len(rows), "last_error": error})
            save_rows(output, rows)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"status": "error", **error}, ensure_ascii=False), file=sys.stderr, flush=True)
        if args.delay_sec > 0 and index < len(months):
            time.sleep(args.delay_sec)
    status.update({"completed": sorted(completed), "errors": errors, "rows": len(rows), "finished_at": datetime.now(timezone.utc).isoformat()})
    save_rows(output, rows)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "complete", "months_processed": len(months), "rows": len(rows), "errors": len(errors), "output": str(output), "keyword_count": len(keywords)}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
