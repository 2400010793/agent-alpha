#!/usr/bin/env python3
"""Resumably synchronize a manifest-pinned OpenAlex snapshot entity.

Only files listed in the selected entity manifest are downloaded. Existing
files with the exact manifest size are reused, and partial files continue via
HTTP Range requests. Deterministic manifest shards allow several Slurm nodes
to share one destination without downloading the same object.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


BUCKET_HTTP = "https://openalex.s3.amazonaws.com/"
USER_AGENT = "paper-graph-openalex-snapshot/0.1"


def request(url: str, *, start: int = 0, timeout: float = 120.0):
    headers = {"User-Agent": USER_AGENT}
    if start:
        headers["Range"] = f"bytes={start}-"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    with request(url, timeout=timeout) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object from {url}")
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def object_url(value: str) -> str:
    prefix = "s3://openalex/"
    if not value.startswith(prefix):
        raise ValueError(f"Unexpected OpenAlex object URL: {value}")
    return BUCKET_HTTP + value[len(prefix):]


def object_path(root: Path, value: str) -> Path:
    marker = "/updated_date="
    if marker not in value:
        raise ValueError(f"Object has no updated_date partition: {value}")
    return root / ("updated_date=" + value.split(marker, 1)[1])


def stratified_files(files: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Select evenly spaced manifest files including both endpoints."""
    if count <= 0 or count >= len(files):
        return files
    if count == 1:
        return [files[len(files) // 2]]
    indexes = {round(index * (len(files) - 1) / (count - 1)) for index in range(count)}
    return [files[index] for index in sorted(indexes)]


def sharded_files(files: list[dict[str, Any]], index: int,
                  count: int) -> list[dict[str, Any]]:
    """Select one deterministic modulo shard while preserving manifest order."""
    if count < 1:
        raise ValueError("shard count must be at least 1")
    if index < 0 or index >= count:
        raise ValueError(f"shard index must be in [0, {count})")
    return [item for position, item in enumerate(files) if position % count == index]


def download(url: str, destination: Path, expected_size: int, timeout: float) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    if destination.exists() and destination.stat().st_size == expected_size:
        return
    if destination.exists():
        destination.unlink()
    start = partial.stat().st_size if partial.exists() else 0
    if start > expected_size:
        partial.unlink()
        start = 0
    with request(url, start=start, timeout=timeout) as response:
        # A server may ignore Range. Avoid appending a complete response to a
        # partial object in that case.
        append = start > 0 and getattr(response, "status", None) == 206
        mode = "ab" if append else "wb"
        with partial.open(mode) as stream:
            shutil.copyfileobj(response, stream, length=16 * 1024 * 1024)
    actual_size = partial.stat().st_size
    if actual_size != expected_size:
        raise IOError(f"Size mismatch for {url}: expected {expected_size}, received {actual_size}")
    partial.replace(destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", default="works")
    parser.add_argument("--format", choices=("parquet", "jsonl"), default="parquet")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path,
                        help="reuse an already pinned manifest instead of fetching the current one")
    parser.add_argument("--max-files", type=int, default=0,
                        help="download at most this many files; 0 means the complete entity")
    parser.add_argument("--sample-files", type=int, default=0,
                        help="download this many evenly spaced manifest files")
    parser.add_argument("--shard-count", type=int, default=1,
                        help="split the selected manifest into this many modulo shards")
    parser.add_argument("--shard-index", type=int, default=0,
                        help="zero-based modulo shard to download")
    parser.add_argument("--min-updated-date")
    parser.add_argument("--max-updated-date")
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--workers", type=int, default=1, help="parallel object downloads")
    args = parser.parse_args()

    manifest_url = f"{BUCKET_HTTP}data/{args.format}/{args.entity}/manifest.json"
    manifest = (
        json.loads(args.manifest.read_text(encoding="utf-8"))
        if args.manifest else fetch_json(manifest_url, args.timeout)
    )
    if manifest.get("entity") != args.entity or manifest.get("format") != args.format:
        raise ValueError("Manifest entity/format does not match requested synchronization")

    snapshot_date = str(manifest["date"])
    root = args.output_root / snapshot_date / args.format / args.entity
    pinned_manifest = root / "manifest.json"
    if pinned_manifest.exists():
        existing = json.loads(pinned_manifest.read_text(encoding="utf-8"))
        if existing != manifest:
            raise RuntimeError(f"Pinned manifest changed at {pinned_manifest}; use a new snapshot directory")
    else:
        atomic_json(pinned_manifest, manifest)

    selected = []
    for item in manifest.get("files") or []:
        value = str(item.get("url") or "")
        partition = value.split("updated_date=", 1)[-1].split("/", 1)[0]
        if args.min_updated_date and partition < args.min_updated_date:
            continue
        if args.max_updated_date and partition > args.max_updated_date:
            continue
        selected.append(item)
    if args.max_files:
        selected = selected[:args.max_files]
    if args.sample_files:
        selected = stratified_files(selected, args.sample_files)
    unsharded_file_count = len(selected)
    selected = sharded_files(selected, args.shard_index, args.shard_count)

    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    completed_bytes = 0
    started = time.time()

    def sync_one(index: int, item: dict[str, Any]) -> tuple[int, Path, int]:
        value = str(item["url"])
        expected_size = int((item.get("meta") or {})["content_length"])
        destination = object_path(root, value)
        for attempt in range(1, args.retries + 1):
            try:
                download(object_url(value), destination, expected_size, args.timeout)
                break
            except (OSError, TimeoutError, urllib.error.URLError) as error:
                if attempt == args.retries:
                    raise
                wait = min(2 ** attempt, 60)
                print(f"retry={attempt} wait={wait}s error={error}", flush=True)
                time.sleep(wait)
        return index, destination, expected_size

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(sync_one, index, item) for index, item in enumerate(selected, 1)]
        for future in as_completed(futures):
            index, destination, expected_size = future.result()
            completed_bytes += expected_size
            print(
                f"[{index}/{len(selected)}] {destination.relative_to(root)} "
                f"bytes={expected_size} completed_bytes={completed_bytes}",
                flush=True,
            )

    summary_name = (
        "sync-summary.json"
        if args.shard_count == 1
        else f"sync-summary-shard-{args.shard_index:05d}-of-{args.shard_count:05d}.json"
    )
    atomic_json(root / summary_name, {
        "snapshot_date": snapshot_date,
        "format": args.format,
        "entity": args.entity,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "unsharded_file_count": unsharded_file_count,
        "selected_file_count": len(selected),
        "selected_content_length": sum(int((item.get("meta") or {})["content_length"]) for item in selected),
        "complete_entity": not args.max_files and not args.sample_files
        and not args.min_updated_date and not args.max_updated_date
        and args.shard_count == 1,
        "workers": args.workers,
        "elapsed_seconds": round(time.time() - started, 3),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
