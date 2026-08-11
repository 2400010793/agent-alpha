#!/usr/bin/env python3
"""Collect arXiv article links for the configured keyword set."""
from __future__ import annotations

import argparse
import json
import random
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from pathlib import Path
from typing import Dict, Iterable, List

from src.pipeline.crawl_arxiv_factor_10y import ROOT, load_search_keywords

ATOM_NS = "http://www.w3.org/2005/Atom"
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"
CATEGORIES = ("q-fin.*", "stat.ML", "econ.EM")
DEFAULT_OUTPUT = ROOT / "data" / "arxiv_85keyword_links_10y.jsonl"
DEFAULT_STATUS = ROOT / "data" / "arxiv_85keyword_links_10y.status.json"
API_URL = "https://arxiv.org/api/query"


def batches(items: List[str], size: int) -> Iterable[List[str]]:
    for index in range(0, len(items), size):
        yield items[index:index + size]


def load_rows(path: Path) -> Dict[str, Dict[str, object]]:
    rows: Dict[str, Dict[str, object]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
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
    return {"completed_batches": [], "errors": []}


def fetch_page(query: str, start: int, page_size: int, timeout: int, retries: int, backoff: float):
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": start,
        "max_results": page_size,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(
                API_URL + "?" + params,
                headers={"User-Agent": "factor-study-keyword-links/1.0"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
            root = ET.fromstring(payload)
            total_text = root.findtext(f"{{{OPENSEARCH_NS}}}totalResults")
            total = int(total_text) if total_text and total_text.isdigit() else None
            entries = root.findall(f"{{{ATOM_NS}}}entry")
            return entries, total
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                retry_after = None
                if isinstance(exc, HTTPError):
                    value = exc.headers.get("Retry-After")
                    if value and value.isdigit():
                        retry_after = float(value)
                time.sleep(max(retry_after or 0.0, backoff * (2 ** attempt)) + random.uniform(0.0, 3.0))
    assert last_error is not None
    raise last_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--keyword-config", type=Path, default=ROOT / "config" / "sources.yaml")
    parser.add_argument("--start-date", default="201607010000")
    parser.add_argument("--end-date", default="202607312359")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--backoff-sec", type=float, default=20.0)
    parser.add_argument("--delay-sec", type=float, default=3.0)
    parser.add_argument("--timeout-sec", type=int, default=120)
    args = parser.parse_args()

    keywords = load_search_keywords(args.keyword_config)
    rows = load_rows(args.output)
    status = load_status(args.status)
    completed = set(status.get("completed_batches") or [])
    errors = list(status.get("errors") or [])
    next_starts = {str(key): int(value) for key, value in (status.get("next_starts") or {}).items()}
    keyword_batches = list(batches(keywords, args.batch_size))

    for batch_index, batch in enumerate(keyword_batches):
        batch_id = str(batch_index)
        if batch_id in completed:
            continue
        query = (
            f"(({' OR '.join('cat:' + category for category in CATEGORIES)}) AND "
            f"({' OR '.join('all:' + keyword for keyword in batch)})) AND "
            f"submittedDate:[{args.start_date} TO {args.end_date}]"
        )
        batch_total = None
        batch_pages = 0
        try:
            start = next_starts.get(batch_id, 0)
            for _ in range(10**9):
                if args.delay_sec > 0:
                    time.sleep(args.delay_sec + random.uniform(0.0, 2.0))
                entries, total = fetch_page(query, start, args.page_size, args.timeout_sec, args.retries, args.backoff_sec)
                batch_total = total if total is not None else batch_total
                batch_pages += 1
                for entry in entries:
                    id_url = entry.findtext(f"{{{ATOM_NS}}}id") or ""
                    arxiv_id = id_url.rsplit("/", 1)[-1].split("v", 1)[0]
                    if not arxiv_id:
                        continue
                    rows[arxiv_id] = {
                        "arxiv_id": arxiv_id,
                        "url": f"https://arxiv.org/abs/{arxiv_id}",
                        "title": (entry.findtext(f"{{{ATOM_NS}}}title") or "").strip(),
                        "published": (entry.findtext(f"{{{ATOM_NS}}}published") or "").strip(),
                        "keyword_batch": batch,
                    }
                next_starts[batch_id] = start + len(entries)
                status.update({
                    "completed_batches": sorted(completed),
                    "next_starts": next_starts,
                    "errors": errors,
                    "rows": len(rows),
                    "keyword_count": len(keywords),
                })
                save_rows(args.output, rows)
                args.status.parent.mkdir(parents=True, exist_ok=True)
                args.status.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                if len(entries) < args.page_size or (batch_total is not None and start + args.page_size >= batch_total):
                    break
                start += len(entries)
            completed.add(batch_id)
            next_starts.pop(batch_id, None)
            status.update({"completed_batches": sorted(completed), "next_starts": next_starts, "errors": errors, "rows": len(rows), "keyword_count": len(keywords)})
            save_rows(args.output, rows)
            args.status.parent.mkdir(parents=True, exist_ok=True)
            args.status.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"status": "ok", "batch": batch_index + 1, "batches": len(keyword_batches), "batch_total": batch_total, "pages": batch_pages, "rows": len(rows)}, ensure_ascii=False), flush=True)
        except Exception as exc:
            error = {"batch": batch_index, "error_type": type(exc).__name__, "error": str(exc)}
            errors.append(error)
            status.update({"completed_batches": sorted(completed), "next_starts": next_starts, "errors": errors, "rows": len(rows), "keyword_count": len(keywords), "last_error": error})
            save_rows(args.output, rows)
            args.status.parent.mkdir(parents=True, exist_ok=True)
            args.status.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"status": "error", **error}, ensure_ascii=False), flush=True)
    status.update({"finished_at": time.time(), "rows": len(rows), "completed_batches": sorted(completed), "next_starts": next_starts, "errors": errors})
    save_rows(args.output, rows)
    args.status.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
