#!/usr/bin/env python3
"""Classify graph papers by available full-text sources.

The default mode is cache-only and never contacts publishers. With
``--probe-network`` it queries OpenAlex for OpenAlex IDs and optionally checks
candidate PDF URLs by content type/signature. DOI and landing-page URLs are
never counted as downloadable files without a successful content check.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote
from typing import Any

ARXIV_RE = re.compile(r"^(?:arxiv:)?(\d{4}\.\d+)(?:v\d+)?$", re.I)
UA = "paper-graph-availability/0.1 (mailto:paper-graph@example.org)"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def graph_papers(root: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for path in root.rglob("graph-*.json"):
        try:
            graph = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for paper in graph.get("nodes", []):
            paper_id = str(paper.get("id") or "")
            if paper_id:
                result.setdefault(paper_id, paper)
    return result


def arxiv_id(value: str) -> str | None:
    match = ARXIV_RE.match(value.strip())
    return match.group(1) if match else None


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def check_pdf(url: str, timeout: float) -> tuple[bool, str, int | None]:
    request = Request(url, headers={"User-Agent": UA, "Range": "bytes=0-7"})
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            prefix = response.read(8)
            is_pdf = prefix.startswith(b"%PDF-") or "application/pdf" in content_type
            return is_pdf, content_type, getattr(response, "status", None)
    except Exception as error:
        return False, f"error:{type(error).__name__}:{error}", None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-root", type=Path, required=True)
    parser.add_argument("--arxiv-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--probe-network", action="store_true")
    parser.add_argument("--check-pdf", action="store_true")
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    papers = graph_papers(args.graph_root)
    cache_path = args.cache or args.output.with_suffix(".openalex-cache.json")
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    tex_ok = {}
    for row in read_jsonl(args.arxiv_manifest):
        ident = arxiv_id(str(row.get("arxiv_id") or ""))
        if ident and row.get("status") == "ok":
            tex_ok[ident] = row

    records = []
    for paper_id, paper in sorted(papers.items()):
        ident = arxiv_id(paper_id)
        if ident:
            if ident in tex_ok:
                status = "arxiv_tex_available"
            else:
                status = "arxiv_pdf_or_tex_unchecked"
            records.append({"paper_id": paper_id, "title": paper.get("title"), "status": status,
                            "arxiv_id": ident, "source_url": f"https://arxiv.org/abs/{ident}"})
            continue

        metadata = paper.get("metadata") or {}
        openalex_id = str(metadata.get("openalex_id") or paper_id)
        if openalex_id.startswith("openalex:"):
            if args.probe_network and openalex_id not in cache:
                try:
                    cache[openalex_id] = fetch_json(
                        f"https://api.openalex.org/works/{quote(openalex_id.split(':', 1)[-1])}", args.timeout)
                except Exception as error:
                    cache[openalex_id] = {"_error": f"{type(error).__name__}: {error}"}
                if args.delay:
                    time.sleep(args.delay)
            payload = cache.get(openalex_id) or {}
            if payload.get("_error"):
                status = "metadata_lookup_failed"
                pdf_url = None
            else:
                locations = payload.get("locations") or []
                pdf_url = next((item.get("pdf_url") for item in locations if item.get("pdf_url")), None)
                oa = payload.get("open_access") or {}
                status = "direct_pdf_candidate" if pdf_url else (
                    "open_access_landing_page" if oa.get("is_oa") else "metadata_only")
                if pdf_url and args.check_pdf:
                    ok, content_type, http_status = check_pdf(str(pdf_url), args.timeout)
                    status = "direct_pdf_available" if ok else "download_failed"
                else:
                    content_type, http_status = None, None
            records.append({"paper_id": paper_id, "title": paper.get("title"), "status": status,
                            "openalex_id": openalex_id, "pdf_url": pdf_url,
                            "landing_page_url": payload.get("primary_location", {}).get("landing_page_url"),
                            "content_type": content_type if 'content_type' in locals() else None,
                            "http_status": http_status if 'http_status' in locals() else None})
        else:
            url = str(paper.get("url") or "")
            records.append({"paper_id": paper_id, "title": paper.get("title"),
                            "status": "landing_page_only" if url else "metadata_only", "source_url": url})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    summary = {"graph_root": str(args.graph_root), "paper_count": len(records), "counts": counts,
               "network_probe": args.probe_network, "pdf_check": args.check_pdf,
               "report": str(args.output)}
    args.output.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
