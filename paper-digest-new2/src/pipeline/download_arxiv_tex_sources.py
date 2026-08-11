#!/usr/bin/env python3
"""Download arXiv TeX source archives for mechanism-category candidates."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.pipeline.crawl_arxiv_by_mechanism_category import (
    CATEGORY_TERMS,
    is_relevant_match,
    match_terms,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEED = ROOT / "data" / "arxiv_mechanism_category_candidates.jsonl"
DEFAULT_METADATA = ROOT / "data" / "arxiv_factor_articles_10y.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "arxiv_tex_sources"
DEFAULT_MANIFEST = ROOT / "data" / "arxiv_tex_sources_manifest.jsonl"
DEFAULT_STATUS = ROOT / "data" / "arxiv_tex_sources.status.json"
USER_AGENT = "factor-study-paper-bot/1.0 (arxiv source downloader)"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def build_seeds(path: Path) -> List[Dict[str, Any]]:
    """Use the categorized seed file, or derive candidates from the old metadata archive."""
    if path.exists():
        return read_jsonl(path)
    seeds: Dict[str, Dict[str, Any]] = {}
    for row in read_jsonl(DEFAULT_METADATA):
        identifier = str(row.get("arxiv_id") or "").strip()
        if not identifier:
            continue
        categories = [category for category in CATEGORY_TERMS if is_relevant_match(match_terms(row, category))]
        if not categories:
            continue
        seed = dict(row)
        seed["candidate_categories"] = categories
        seed["source_id"] = seed.get("source_id") or "arxiv_factor_10y"
        seed["source_name"] = seed.get("source_name") or "arXiv factor metadata"
        seeds[identifier] = seed
    return list(seeds.values())


def load_status(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"completed": [], "failed": [], "updated_at": now()}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"completed": [], "failed": []}
    except json.JSONDecodeError:
        return {"completed": [], "failed": []}


def save_status(path: Path, status: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def source_url(identifier: str) -> str:
    return f"https://export.arxiv.org/e-print/{urllib.parse.quote(identifier)}"


def download_one(identifier: str, destination: Path, timeout_sec: int) -> int:
    request = urllib.request.Request(source_url(identifier), headers={"User-Agent": USER_AGENT})
    temporary = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        total = 0
        with temporary.open("wb") as handle:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                handle.write(block)
                total += len(block)
        temporary.replace(destination)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-path", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument("--delay-sec", type=float, default=10.0)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    seeds = build_seeds(args.seed_path)
    if args.limit > 0:
        seeds = seeds[: args.limit]
    status = load_status(args.status)
    completed = set(str(x) for x in status.get("completed") or [])
    failed = set(str(x) for x in status.get("failed") or [])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    attempted = 0
    succeeded = 0

    for seed in seeds:
        identifier = str(seed.get("arxiv_id") or "").strip()
        if not identifier or identifier in completed or (identifier in failed and not args.retry_failed):
            continue
        destination = args.output_dir / f"{identifier.replace('/', '_')}.source"
        attempted += 1
        record: Dict[str, Any] = {
            "arxiv_id": identifier,
            "title": seed.get("title"),
            "url": seed.get("url") or f"https://arxiv.org/abs/{identifier}",
            "source_url": source_url(identifier),
            "candidate_categories": seed.get("candidate_categories") or [],
            "path": str(destination),
            "started_at": now(),
        }
        try:
            if destination.exists() and destination.stat().st_size > 0:
                size = destination.stat().st_size
            else:
                size = download_one(identifier, destination, args.timeout_sec)
            completed.add(identifier)
            failed.discard(identifier)
            succeeded += 1
            record.update({"status": "ok", "bytes": size, "finished_at": now()})
            print(json.dumps({"status": "ok", "arxiv_id": identifier, "bytes": size, "categories": record["candidate_categories"]}, ensure_ascii=False), flush=True)
        except Exception as exc:
            failed.add(identifier)
            record.update({"status": "failed", "error_type": type(exc).__name__, "error": str(exc), "finished_at": now()})
            print(json.dumps({"status": "failed", "arxiv_id": identifier, "error": str(exc)}, ensure_ascii=False), flush=True)
        append_jsonl(args.manifest, record)
        status.update({"completed": sorted(completed), "failed": sorted(failed), "seed_count": len(seeds), "attempted": attempted, "succeeded": succeeded, "updated_at": now()})
        save_status(args.status, status)
        if args.delay_sec > 0:
            time.sleep(args.delay_sec)

    status.update({"completed": sorted(completed), "failed": sorted(failed), "seed_count": len(seeds), "attempted": attempted, "succeeded": succeeded, "finished_at": now()})
    save_status(args.status, status)
    print(json.dumps({"status": "complete", "seed_count": len(seeds), "attempted": attempted, "succeeded": succeeded, "failed": len(failed), "manifest": str(args.manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
