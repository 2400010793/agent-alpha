#!/usr/bin/env python3
"""Collect arXiv links through the OpenAlex works API.

OpenAlex is used as a fallback index when the arXiv API is rate-limited. The
result is an independent JSONL pool and never modifies the existing arXiv
metadata pool.
"""
from __future__ import annotations

import argparse
import json
import random
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError

from src.pipeline.crawl_arxiv_factor_10y import ROOT, load_search_keywords

DEFAULT_OUTPUT = ROOT / "data" / "arxiv_85keyword_openalex_links_10y.jsonl"
DEFAULT_STATUS = ROOT / "data" / "arxiv_85keyword_openalex_links_10y.status.json"
OPENALEX_URL = "https://api.openalex.org/works"
ARXIV_SOURCE_ID = "S4306400194"  # arXiv (Cornell University) in OpenAlex


class RateLimitError(RuntimeError):
    """Raised when OpenAlex asks the crawler to stop sending requests."""


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
    path.write_text(
        "".join(json.dumps(rows[key], ensure_ascii=False) + "\n" for key in sorted(rows)),
        encoding="utf-8",
    )


def load_status(path: Path) -> Dict[str, object]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"completed_keywords": [], "skipped_keywords": [], "errors": [], "next_cursors": {}}


def arxiv_id(work: Dict[str, object]) -> str:
    """Extract an arXiv identifier from OpenAlex IDs or location URLs."""
    ids = work.get("ids")
    candidates: List[object] = []
    if isinstance(ids, dict):
        candidates.append(ids.get("arxiv"))
    locations = work.get("locations")
    if isinstance(locations, list):
        for location in locations:
            if not isinstance(location, dict):
                continue
            candidates.extend((location.get("landing_page_url"), location.get("pdf_url")))
    for value in candidates:
        if not isinstance(value, str) or "arxiv.org/" not in value:
            continue
        identifier = value.rstrip("/").rsplit("/", 1)[-1].split("v", 1)[0]
        if identifier:
            return identifier
    return ""


def _retry_delay(exc: Exception, backoff: float, attempt: int) -> float:
    if isinstance(exc, HTTPError):
        value = exc.headers.get("Retry-After")
        if value and value.isdigit():
            return max(float(value), backoff * (2**attempt))
    return backoff * (2**attempt)


def fetch_page(
    keyword: str,
    cursor: str,
    *,
    start_date: str,
    end_date: str,
    per_page: int,
    timeout: int,
    retries: int,
    backoff: float,
    mailto: str,
) -> Tuple[List[Dict[str, object]], Optional[str], int]:
    params = {
        "search": keyword,
        # Restrict the search to the OpenAlex source representing arXiv. This
        # avoids scanning thousands of non-arXiv works before local ID checks.
        "filter": (
            f"from_publication_date:{start_date},"
            f"to_publication_date:{end_date},"
            f"locations.source.id:{ARXIV_SOURCE_ID}"
        ),
        "per-page": str(per_page),
        "cursor": cursor,
    }
    if mailto:
        params["mailto"] = mailto
    url = OPENALEX_URL + "?" + urllib.parse.urlencode(params)
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "factor-study-openalex-links/1.0"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
            data = json.loads(payload)
            results = data.get("results") or []
            meta = data.get("meta") or {}
            next_cursor = meta.get("next_cursor")
            return results, str(next_cursor) if next_cursor else None, attempt
        except HTTPError as exc:
            if exc.code == 429:
                raise RateLimitError(f"OpenAlex HTTP 429 for keyword {keyword}") from exc
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(_retry_delay(exc, backoff, attempt) + random.uniform(0.0, 2.0))
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(_retry_delay(exc, backoff, attempt) + random.uniform(0.0, 2.0))
    assert last_error is not None
    raise last_error


def save_checkpoint(
    path: Path,
    *,
    completed: Iterable[str],
    skipped: Iterable[str],
    errors: List[Dict[str, object]],
    next_cursors: Dict[str, str],
    rows: int,
    keyword_count: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    status = {
        "completed_keywords": sorted(completed),
        "skipped_keywords": sorted(skipped),
        "errors": errors,
        "next_cursors": next_cursors,
        "rows": rows,
        "keyword_count": keyword_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--keyword-config", type=Path, default=ROOT / "config" / "sources.yaml")
    parser.add_argument("--start-date", default="2016-07-01")
    parser.add_argument("--end-date", default="2026-07-31")
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--max-pages-per-keyword", type=int, default=100)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--backoff-sec", type=float, default=10.0)
    parser.add_argument("--delay-sec", type=float, default=2.0)
    parser.add_argument("--timeout-sec", type=int, default=60)
    parser.add_argument("--mailto", default="", help="Optional email for the OpenAlex polite pool")
    args = parser.parse_args()

    keywords = load_search_keywords(args.keyword_config)
    if not keywords:
        raise SystemExit(f"No keywords found in {args.keyword_config}")
    rows = load_rows(args.output)
    status = load_status(args.status)
    completed = set(str(value) for value in status.get("completed_keywords") or [])
    skipped = set(str(value) for value in status.get("skipped_keywords") or [])
    errors = list(status.get("errors") or [])
    next_cursors = {str(key): str(value) for key, value in (status.get("next_cursors") or {}).items()}

    for index, keyword in enumerate(keywords, 1):
        if keyword in completed:
            continue
        cursor = next_cursors.get(keyword, "*")
        pages = 0
        try:
            while cursor and pages < args.max_pages_per_keyword:
                if args.delay_sec > 0:
                    time.sleep(args.delay_sec + random.uniform(0.0, 1.0))
                works, next_cursor, attempts = fetch_page(
                    keyword,
                    cursor,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    per_page=args.per_page,
                    timeout=args.timeout_sec,
                    retries=args.retries,
                    backoff=args.backoff_sec,
                    mailto=args.mailto,
                )
                pages += 1
                for work in works:
                    identifier = arxiv_id(work)
                    if not identifier:
                        continue
                    primary_location = work.get("primary_location") or {}
                    source = primary_location.get("source") if isinstance(primary_location, dict) else {}
                    rows[identifier] = {
                        "arxiv_id": identifier,
                        "url": f"https://arxiv.org/abs/{identifier}",
                        "title": str(work.get("title") or "").strip(),
                        "published": str(work.get("publication_date") or "").strip(),
                        "openalex_id": work.get("id"),
                        "openalex_url": work.get("doi") or work.get("id"),
                        "keyword": keyword,
                        "source_name": "OpenAlex arXiv keyword fallback",
                        "source": source.get("display_name") if isinstance(source, dict) else None,
                    }
                cursor = next_cursor or ""
                if cursor:
                    next_cursors[keyword] = cursor
                else:
                    next_cursors.pop(keyword, None)
                save_rows(args.output, rows)
                save_checkpoint(args.status, completed=completed, skipped=skipped, errors=errors, next_cursors=next_cursors, rows=len(rows), keyword_count=len(keywords))
                print(json.dumps({"status": "page", "keyword": keyword, "progress": f"{index}/{len(keywords)}", "page": pages, "received": len(works), "attempts": attempts, "rows": len(rows)}, ensure_ascii=False), flush=True)
            if cursor:
                raise RuntimeError(f"max pages reached for keyword: {keyword}")
            completed.add(keyword)
            next_cursors.pop(keyword, None)
            save_checkpoint(args.status, completed=completed, skipped=skipped, errors=errors, next_cursors=next_cursors, rows=len(rows), keyword_count=len(keywords))
            print(json.dumps({"status": "ok", "keyword": keyword, "pages": pages, "rows": len(rows)}, ensure_ascii=False), flush=True)
        except Exception as exc:
            error = {"keyword": keyword, "error_type": type(exc).__name__, "error": str(exc), "ts": datetime.now(timezone.utc).isoformat()}
            errors.append(error)
            # A failed keyword must not block the rest of the configured set.
            # Keep its partial rows and mark it as skipped for resumability.
            completed.add(keyword)
            skipped.add(keyword)
            next_cursors.pop(keyword, None)
            save_rows(args.output, rows)
            save_checkpoint(args.status, completed=completed, skipped=skipped, errors=errors, next_cursors=next_cursors, rows=len(rows), keyword_count=len(keywords))
            print(json.dumps({"status": "error", **error}, ensure_ascii=False), flush=True)

    save_rows(args.output, rows)
    save_checkpoint(args.status, completed=completed, skipped=skipped, errors=errors, next_cursors=next_cursors, rows=len(rows), keyword_count=len(keywords))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
