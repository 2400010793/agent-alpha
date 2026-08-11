#!/usr/bin/env python3
"""Count Graph works that OpenAlex associates with arXiv.

All Graph nodes already carry OpenAlex IDs. The scan queries each Work and
checks explicit ids.arxiv, arXiv DOI, arXiv source locations, and arXiv URLs.
Results and cache are checkpointed periodically so the scan is resumable.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen
from typing import Any

ARXIV_ID = re.compile(r"(?:arxiv[:/]|arxiv\.org/(?:abs|pdf)/|10\.48550/arxiv\.)([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?", re.I)
UA = "paper-graph-arxiv-audit/0.1 (mailto:paper-graph@example.org)"


def graph_ids(root: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for path in root.glob("*/graph-*.json"):
        try:
            graph = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for node in graph.get("nodes") or []:
            node_id = str(node.get("id") or "")
            if node_id.startswith("openalex:"):
                result.setdefault(node_id, node)
    return result


def fetch(openalex_id: str, timeout: float) -> dict[str, Any]:
    url = f"https://api.openalex.org/works/{openalex_id.split(':', 1)[-1]}"
    request = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def extract(payload: dict[str, Any]) -> tuple[str | None, str]:
    ids = payload.get("ids") or {}
    direct = str(ids.get("arxiv") or "")
    match = ARXIV_ID.search(direct)
    if match:
        return match.group(1), "ids.arxiv"
    doi = str(payload.get("doi") or "")
    match = ARXIV_ID.search(doi)
    if match:
        return match.group(1), "doi"
    for location in payload.get("locations") or []:
        source = location.get("source") or {}
        text = " ".join(str(location.get(key) or "") for key in ("landing_page_url", "pdf_url", "raw_source_name"))
        text += " " + str(source.get("display_name") or "") + " " + str(source.get("id") or "")
        if "arxiv" in text.lower():
            match = ARXIV_ID.search(text)
            return (match.group(1) if match else None), "location_arxiv" if match else "location_arxiv_without_id"
    return None, "none"


def save(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    args = parser.parse_args()
    nodes = graph_ids(args.graph_root)
    cache = json.loads(args.cache.read_text(encoding="utf-8")) if args.cache.exists() else {}
    records = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {}
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pending = [key for key in sorted(nodes) if key not in cache]
    print(json.dumps({"graph_unique_nodes": len(nodes), "cached": len(cache), "pending": len(pending)}, ensure_ascii=False), flush=True)
    for index, work_id in enumerate(pending, 1):
        try:
            payload = fetch(work_id, args.timeout)
            arxiv_id, source = extract(payload)
            cache[work_id] = {"payload": payload}
            records[work_id] = {"paper_id": work_id, "title": nodes[work_id].get("title"),
                                "arxiv_id": arxiv_id, "arxiv_source": source,
                                "openalex_ids": payload.get("ids") or {},
                                "doi": payload.get("doi"), "status": "arxiv_linked" if arxiv_id else "not_arxiv_linked"}
        except Exception as error:
            cache[work_id] = {"_error": f"{type(error).__name__}: {error}"}
            records[work_id] = {"paper_id": work_id, "title": nodes[work_id].get("title"),
                                "status": "lookup_failed", "error": str(error)}
        if index % args.checkpoint_every == 0:
            save(args.cache, cache)
            save(args.output, records)
            print(json.dumps({"done": index, "total": len(pending), "linked": sum(r.get("status") == "arxiv_linked" for r in records.values()), "failed": sum(r.get("status") == "lookup_failed" for r in records.values())}), flush=True)
        if args.delay:
            time.sleep(args.delay)
    save(args.cache, cache)
    save(args.output, records)
    counts = {}
    for row in records.values(): counts[row["status"]] = counts.get(row["status"], 0) + 1
    summary = {"graph_unique_nodes": len(nodes), "records": len(records), "counts": counts,
               "unique_arxiv_ids": len({r.get("arxiv_id") for r in records.values() if r.get("arxiv_id")}),
               "output": str(args.output), "cache": str(args.cache)}
    args.output.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
