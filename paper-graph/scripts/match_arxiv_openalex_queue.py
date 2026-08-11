#!/usr/bin/env python3
"""Resolve a screened arXiv queue to OpenAlex with local-first checkpoints.

The matcher never uses the retired ``ids.arxiv`` OpenAlex filter. It first
reuses local exports, then optionally performs one arXiv-source title search
per pending record. Every record is written immediately so interruption is
safe and failures do not block the remainder of the queue.
"""
from __future__ import annotations

import argparse
import difflib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

OPENALEX_API = "https://api.openalex.org/works"
ARXIV_SOURCE = "S4306400194"
USER_AGENT = "paper-graph-arxiv-openalex-matcher/0.2"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix == ".json":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if isinstance(value, dict):
            return [{**row, "arxiv_id": row.get("arxiv_id") or key}
                    for key, row in value.items() if isinstance(row, dict)]
        return value if isinstance(value, list) else []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def title_key(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def local_index(paths: list[Path]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for path in paths:
        for row in load_jsonl(path):
            ident = str(row.get("arxiv_id") or "").split("v", 1)[0]
            nested = row.get("openalex") if isinstance(row.get("openalex"), dict) else {}
            openalex_id = row.get("openalex_id") or row.get("paper_id") or nested.get("openalex_id")
            if ident and openalex_id:
                normalized = dict(row)
                normalized["openalex_id"] = str(openalex_id).split(":", 1)[-1]
                # A queue row may still carry its queue-level ``status``
                # (usually ``pending``); it must not overwrite the identity
                # status when reused as a local match.
                normalized.pop("status", None)
                index.setdefault(ident, normalized)
    return index


def request_json(url: str, timeout: float, retries: int, cooldown: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            last = error
            if error.code not in {408, 429, 500, 502, 503, 504}:
                raise
            retry_after = error.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.isdigit() else cooldown * (2 ** attempt)
            time.sleep(min(wait, 300.0))
        except (TimeoutError, urllib.error.URLError) as error:
            last = error
            time.sleep(min(cooldown * (2 ** attempt), 300.0))
    raise RuntimeError(f"OpenAlex request failed after {retries} attempts: {last}")


def match_online(row: dict[str, Any], timeout: float, retries: int, cooldown: float) -> dict[str, Any]:
    # Resolve the canonical arXiv DOI first. Title search is only a fallback,
    # because broad search results can be related but different papers.
    arxiv_id = str(row.get("arxiv_id") or "").split("v", 1)[0]
    doi_url = f"{OPENALEX_API}/doi:10.48550/arxiv.{urllib.parse.quote(arxiv_id, safe='')}"
    try:
        item = request_json(doi_url, timeout, retries, cooldown)
        identifier = str(item.get("id") or "")
        return {"status": "matched", "match_method": "arxiv_doi",
                "arxiv_id": row.get("arxiv_id"), "title_score": 1.0,
                "openalex_id": identifier.rsplit("/", 1)[-1], "openalex_url": identifier,
                "title": item.get("title"), "doi": item.get("doi"),
                "publication_year": item.get("publication_year"),
                "cited_by_count": item.get("cited_by_count", 0),
                "open_access": item.get("open_access"), "topics": item.get("topics") or [],
                "concepts": item.get("concepts") or []}
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise

    params = urllib.parse.urlencode({
        "search": row.get("title", ""),
        "filter": f"locations.source.id:{ARXIV_SOURCE}",
        "per-page": 25,
    })
    payload = request_json(f"{OPENALEX_API}?{params}", timeout, retries, cooldown)
    wanted = title_key(row.get("title"))
    ranked = []
    for item in payload.get("results") or []:
        score = difflib.SequenceMatcher(None, wanted, title_key(item.get("title"))).ratio()
        ranked.append((score, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    if not ranked or ranked[0][0] < 0.95:
        return {"status": "not_indexed", "match_method": "title_arxiv_source",
                "arxiv_id": row.get("arxiv_id"), "title_score": round(ranked[0][0], 4) if ranked else 0.0}
    score, item = ranked[0]
    identifier = str(item.get("id") or "")
    return {"status": "matched", "match_method": "title_arxiv_source",
            "arxiv_id": row.get("arxiv_id"), "title_score": round(score, 4),
            "openalex_id": identifier.rsplit("/", 1)[-1], "openalex_url": identifier,
            "title": item.get("title"), "doi": item.get("doi"),
            "publication_year": item.get("publication_year"),
            "cited_by_count": item.get("cited_by_count", 0),
            "open_access": item.get("open_access"), "topics": item.get("topics") or [],
            "concepts": item.get("concepts") or []}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=root / "docs/generated/arxiv-factor-8732-openalex-queue.jsonl")
    parser.add_argument("--output", type=Path, default=root / "docs/generated/arxiv-factor-8732-openalex-matches.jsonl")
    parser.add_argument("--local", action="append", type=Path, default=[])
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--cooldown", type=float, default=30.0)
    parser.add_argument("--max-online", type=int, default=0)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--retry-failed", action="store_true",
                        help="retry previous lookup_failed/not_checked records")
    args = parser.parse_args()
    local_paths = args.local or [
        root / "docs/generated/arxiv-factor-8732-finance-openalex.jsonl",
        root / "docs/generated/graph-arxiv-openalex-v1.json",
        root.parent / "my-paper-digest-new2/data/arxiv_85keyword_openalex_links_10y.jsonl",
    ]
    index = local_index(local_paths)
    done = {str(r.get("arxiv_id")): r for r in load_jsonl(args.output)}
    queue = load_jsonl(args.queue)
    online_count = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as handle:
        for row in queue:
            ident = str(row.get("arxiv_id") or "")
            if not ident:
                result = {**row, "openalex": {"status": "invalid_arxiv_id", "match_method": "missing_arxiv_id"}}
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                handle.flush()
                continue
            previous = done.get(ident)
            previous_status = (previous or {}).get("openalex", {}).get("status")
            terminal = {"matched", "not_indexed", "arxiv_linked"}
            if previous and (previous_status in terminal or not args.retry_failed):
                continue
            if ident in index:
                result = {**row, "openalex": {"status": "matched", "match_method": "local", **index[ident]}}
            elif args.offline:
                result = {**row, "openalex": {"status": "not_checked", "match_method": "offline"}}
            elif args.max_online and online_count >= args.max_online:
                break
            else:
                try:
                    result = {**row, "openalex": match_online(row, args.timeout, args.retries, args.cooldown)}
                except Exception as error:
                    result = {**row, "openalex": {"status": "lookup_failed", "arxiv_id": ident,
                                                   "error": f"{type(error).__name__}: {error}"}}
                online_count += 1
                time.sleep(args.cooldown)
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            handle.flush()
            done[ident] = result
            print(json.dumps({"arxiv_id": ident, "status": result["openalex"]["status"],
                              "processed": len(done), "online": online_count}, ensure_ascii=False), flush=True)
    counts: dict[str, int] = {}
    for row in done.values():
        status = row.get("openalex", {}).get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    print(json.dumps({"queue": len(queue), "processed": len(done), "online_requests": online_count,
                      "counts": counts, "output": str(args.output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())