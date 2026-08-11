#!/usr/bin/env python3
"""Discover post-2016 finance-related arXiv papers and resolve OpenAlex IDs.

The discovery side starts from arXiv, using the project's 85-keyword list and
finance-adjacent arXiv categories. Each canonical arXiv ID is then resolved
with OpenAlex's exact ``ids.arxiv`` filter. Results are checkpointed by month
and OpenAlex response cache, so the scan can be resumed safely.
"""
from __future__ import annotations

import argparse
import calendar
import difflib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ARXIV_API = "https://arxiv.org/api/query"
OPENALEX_API = "https://api.openalex.org/works"
OPENALEX_ARXIV_SOURCE = "S4306400194"
ATOM = "http://www.w3.org/2005/Atom"
OPEN_SEARCH = "http://a9.com/-/spec/opensearch/1.1/"
ARXIV_ID = re.compile(r"(?:arxiv:|arxiv\.org/(?:abs|pdf)/)?([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?$", re.I)
CATEGORIES = ("q-fin.CP", "q-fin.EC", "q-fin.GN", "q-fin.MF", "q-fin.PM", "q-fin.PR", "q-fin.RM", "q-fin.ST", "q-fin.TR", "stat.ML", "econ.EM")
USER_AGENT = "paper-graph-arxiv-finance-discovery/0.1 (mailto:paper-graph@example.org)"


def canonical_arxiv(value: str) -> str | None:
    match = ARXIV_ID.search(value.strip())
    return match.group(1) if match else None


def load_keywords(path: Path) -> list[str]:
    keywords: list[str] = []
    active = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line == "keywords:":
            active = True
            continue
        if active and line and not line.startswith("-"):
            break
        if active and line.startswith("-"):
            value = line[1:].strip().strip("'\"")
            if value and value not in keywords:
                keywords.append(value)
    return keywords


def get(url: str, timeout: float, retries: int = 5) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml, application/json"})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code not in {408, 429, 500, 502, 503, 504} or attempt == retries - 1:
                raise
            retry_after = error.headers.get("Retry-After")
            try:
                wait = max(10.0, float(retry_after)) if retry_after else 15.0 * (2 ** attempt)
            except ValueError:
                wait = 15.0 * (2 ** attempt)
            time.sleep(min(wait, 180.0))
        except (TimeoutError, urllib.error.URLError) as error:
            last_error = error
            if attempt == retries - 1:
                raise
            time.sleep(min(15.0 * (2 ** attempt), 180.0))
    raise RuntimeError(f"request failed: {last_error}")


def month_range(month: str) -> tuple[str, str]:
    year, number = int(month[:4]), int(month[4:])
    last = calendar.monthrange(year, number)[1]
    return f"{month}010000", f"{month}{last:02d}2359"


def parse_feed(payload: bytes) -> tuple[list[dict[str, Any]], int | None]:
    root = ET.fromstring(payload)
    total_text = root.findtext(f"{{{OPEN_SEARCH}}}totalResults")
    total = int(total_text) if total_text and total_text.isdigit() else None
    rows = []
    for entry in root.findall(f"{{{ATOM}}}entry"):
        link = next((x.attrib.get("href", "") for x in entry.findall(f"{{{ATOM}}}link") if x.attrib.get("rel") == "alternate"), "")
        ident = canonical_arxiv(link or entry.findtext(f"{{{ATOM}}}id", ""))
        if not ident:
            continue
        rows.append({
            "arxiv_id": ident,
            "title": " ".join((entry.findtext(f"{{{ATOM}}}title", "") or "").split()),
            "summary": " ".join((entry.findtext(f"{{{ATOM}}}summary", "") or "").split()),
            "published": entry.findtext(f"{{{ATOM}}}published", ""),
            "updated": entry.findtext(f"{{{ATOM}}}updated", ""),
            "authors": [a.findtext(f"{{{ATOM}}}name", "") for a in entry.findall(f"{{{ATOM}}}author")],
            "categories": [c.attrib.get("term", "") for c in entry.findall(f"{{{ATOM}}}category")],
            "url": f"https://arxiv.org/abs/{ident}",
        })
    return rows, total


def query_month(month: str, keywords: list[str], start: int, page_size: int, timeout: float) -> tuple[list[dict[str, Any]], int | None]:
    date_start, date_end = month_range(month)
    category_query = " OR ".join(f"cat:{x}" for x in CATEGORIES)
    term_query = " OR ".join(f"all:{x}" for x in keywords)
    query = f"(({category_query}) AND ({term_query})) AND submittedDate:[{date_start} TO {date_end}]"
    params = urllib.parse.urlencode({"search_query": query, "start": start, "max_results": page_size, "sortBy": "submittedDate", "sortOrder": "descending"})
    return parse_feed(get(f"{ARXIV_API}?{params}", timeout))


def query_month_batches(month: str, keywords: list[str], page_size: int, max_pages: int, batch_size: int, timeout: float) -> tuple[list[dict[str, Any]], int]:
    """Query bounded keyword batches because arXiv rejects oversized queries."""
    rows: dict[str, dict[str, Any]] = {}
    batches = [keywords[i:i + batch_size] for i in range(0, len(keywords), batch_size)]
    for batch in batches:
        for page in range(max_pages):
            entries, total = query_month(month, batch, page * page_size, page_size, timeout)
            for entry in entries:
                rows[entry["arxiv_id"]] = entry
            if len(entries) < page_size or (total is not None and (page + 1) * page_size >= total):
                break
            time.sleep(10.0)
    return list(rows.values()), len(batches)


def _title_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def openalex_match(row: dict[str, Any], timeout: float) -> dict[str, Any]:
    arxiv_id = str(row["arxiv_id"])
    params = urllib.parse.urlencode({"filter": f"ids.arxiv:{arxiv_id}", "per-page": 1})
    try:
        payload = json.loads(get(f"{OPENALEX_API}?{params}", timeout).decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code != 400:
            raise
        # OpenAlex currently rejects ids.arxiv as a filter field. Fall back to
        # an arXiv-source title search and accept only a near-exact title.
        search = urllib.parse.urlencode({"search": row.get("title", ""), "filter": f"locations.source.id:{OPENALEX_ARXIV_SOURCE}", "per-page": 25})
        payload = json.loads(get(f"{OPENALEX_API}?{search}", timeout).decode("utf-8"))
        wanted = _title_key(str(row.get("title") or ""))
        candidates = []
        for item in payload.get("results") or []:
            score = difflib.SequenceMatcher(None, wanted, _title_key(str(item.get("title") or ""))).ratio()
            candidates.append((score, item))
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        if not candidates or candidates[0][0] < 0.95:
            return {"status": "not_indexed", "match_method": "title_arxiv_source", "arxiv_id": arxiv_id, "title_score": candidates[0][0] if candidates else 0.0}
        item = candidates[0][1]
        return {"status": "matched", "match_method": "title_arxiv_source", "title_score": round(candidates[0][0], 4), "arxiv_id": arxiv_id,
                "openalex_id": str(item.get("id") or "").rsplit("/", 1)[-1], "openalex_url": item.get("id"), "title": item.get("title"),
                "doi": item.get("doi"), "publication_year": item.get("publication_year"), "cited_by_count": item.get("cited_by_count", 0),
                "open_access": item.get("open_access"), "topics": item.get("topics") or [], "concepts": item.get("concepts") or []}
    results = payload.get("results") or []
    if not results:
        return {"status": "not_indexed", "match_method": "arxiv_id", "arxiv_id": arxiv_id}
    item = results[0]
    openalex_url = str(item.get("id") or "")
    return {"status": "matched", "match_method": "arxiv_id", "arxiv_id": arxiv_id,
            "openalex_id": openalex_url.rsplit("/", 1)[-1], "openalex_url": openalex_url,
            "title": item.get("title"), "doi": item.get("doi"),
            "publication_year": item.get("publication_year"), "cited_by_count": item.get("cited_by_count", 0),
            "open_access": item.get("open_access"), "topics": item.get("topics") or [], "concepts": item.get("concepts") or []}


def iter_months(start: str, end: str):
    year, number = int(start[:4]), int(start[4:])
    end_value = (int(end[:4]), int(end[4:]))
    while (year, number) <= end_value:
        yield f"{year:04d}{number:02d}"
        number += 1
        if number == 13:
            year, number = year + 1, 1


def write_jsonl(path: Path, rows: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(rows[k], ensure_ascii=False) + "\n" for k in sorted(rows)), encoding="utf-8")


def read_jsonl_map(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--keyword-config", type=Path, default=root.parent / "my-paper-digest-new2/config/sources.yaml")
    parser.add_argument("--output", type=Path, default=root / "docs/generated/arxiv-finance-openalex-2016plus.jsonl")
    parser.add_argument("--raw-output", type=Path, default=root / "docs/generated/arxiv-finance-2016plus-raw.jsonl")
    parser.add_argument("--cache", type=Path, default=root / "docs/generated/arxiv-finance-openalex-2016plus.cache.json")
    parser.add_argument("--status", type=Path, default=root / "docs/generated/arxiv-finance-openalex-2016plus.status.json")
    parser.add_argument("--start-month", default="201601")
    parser.add_argument("--end-month", default=datetime.now(timezone.utc).strftime("%Y%m"))
    parser.add_argument("--limit-months", type=int, default=0)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--keyword-batch-size", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--openalex-delay", type=float, default=0.2)
    parser.add_argument("--skip-openalex", action="store_true")
    args = parser.parse_args()
    keywords = load_keywords(args.keyword_config)
    if len(keywords) != 85:
        raise SystemExit(f"expected 85 keywords, found {len(keywords)} in {args.keyword_config}")
    raw = read_jsonl_map(args.raw_output)
    results: dict[str, dict[str, Any]] = {}
    cache = json.loads(args.cache.read_text(encoding="utf-8")) if args.cache.exists() else {}
    status = json.loads(args.status.read_text(encoding="utf-8")) if args.status.exists() else {"completed_months": [], "errors": []}
    completed = set(status.get("completed_months") or [])
    months = [m for m in iter_months(args.start_month, args.end_month) if m not in completed]
    if args.limit_months:
        months = months[:args.limit_months]
    for month in months:
        try:
            month_rows: dict[str, dict[str, Any]] = {}
            entries, batch_count = query_month_batches(month, keywords, args.page_size, args.max_pages, args.keyword_batch_size, args.timeout)
            for row in entries:
                row["keyword_count"] = len(keywords)
                row["source"] = "arxiv_85_keyword_categories"
                month_rows[row["arxiv_id"]] = row
            raw.update(month_rows)
            completed.add(month)
            write_jsonl(args.raw_output, raw)
            status.update({"completed_months": sorted(completed), "rows": len(raw), "last_success": month, "keyword_count": len(keywords)})
            args.status.parent.mkdir(parents=True, exist_ok=True)
            args.status.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"month": month, "added": len(month_rows), "rows": len(raw), "keyword_batches": batch_count}, ensure_ascii=False), flush=True)
        except Exception as error:
            status.setdefault("errors", []).append({"month": month, "error": f"{type(error).__name__}: {error}"})
            args.status.parent.mkdir(parents=True, exist_ok=True)
            args.status.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"month": month, "status": "error", "error": str(error)}, ensure_ascii=False), flush=True)
    if not args.skip_openalex:
        for index, arxiv_id in enumerate(sorted(raw), 1):
            if arxiv_id in cache:
                match = cache[arxiv_id]
            else:
                try:
                    match = openalex_match(raw[arxiv_id], args.timeout)
                except Exception as error:
                    match = {"status": "lookup_failed", "arxiv_id": arxiv_id, "error": f"{type(error).__name__}: {error}"}
                cache[arxiv_id] = match
                if args.openalex_delay:
                    time.sleep(args.openalex_delay)
            results[arxiv_id] = {**raw[arxiv_id], "openalex": match}
            if index % 25 == 0:
                args.cache.parent.mkdir(parents=True, exist_ok=True)
                args.cache.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                write_jsonl(args.output, results)
                print(json.dumps({"openalex_done": index, "total": len(raw)}, ensure_ascii=False), flush=True)
    else:
        results = {k: {**v, "openalex": {"status": "not_checked"}} for k, v in raw.items()}
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    args.cache.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    write_jsonl(args.output, results)
    counts: dict[str, int] = {}
    for row in results.values():
        key = row["openalex"]["status"]
        counts[key] = counts.get(key, 0) + 1
    summary = {"raw_rows": len(raw), "result_rows": len(results), "openalex_counts": counts, "keyword_count": len(keywords), "start_month": args.start_month, "end_month": args.end_month}
    args.output.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
