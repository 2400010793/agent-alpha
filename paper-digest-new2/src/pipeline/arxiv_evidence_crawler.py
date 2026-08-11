#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Set

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.arxiv.evidence_pack import build_arxiv_evidence_pack  # noqa: E402

DEFAULT_SEED_PATH = ROOT / "data" / "arxiv_seed_articles_from_new_daily_all_resolved_unique.jsonl"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "arxiv_evidence_archive.jsonl"
DEFAULT_STATE_PATH = ROOT / "data" / "runtime" / "arxiv_evidence_crawler_state.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    if not path.exists():
        return rows
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps({"warning": "skip_bad_jsonl", "path": str(path), "line": line_no}, ensure_ascii=False), flush=True)
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def append_jsonl(path: Path, row: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def arxiv_id_of(row: Dict[str, object]) -> str:
    pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
    return str(row.get("arxiv_id") or pack.get("arxiv_id") or "").strip()


def done_ids(rows: Iterable[Dict[str, object]], *, retry_failed: bool) -> Set[str]:
    ids: Set[str] = set()
    for row in rows:
        arxiv_id = arxiv_id_of(row)
        if not arxiv_id:
            continue
        pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
        if retry_failed and str(pack.get("status") or "") != "ok":
            continue
        ids.add(arxiv_id)
    return ids


def select_next_seed(seeds: Iterable[Dict[str, object]], done: Set[str]) -> Dict[str, object] | None:
    for seed in seeds:
        arxiv_id = arxiv_id_of(seed)
        if arxiv_id and arxiv_id not in done:
            return seed
    return None


def crawl_one(args: argparse.Namespace) -> Dict[str, object]:
    seeds = read_jsonl(args.seed_path)
    done = done_ids(read_jsonl(args.output_path), retry_failed=args.retry_failed)
    seed = select_next_seed(seeds, done)
    if seed is None:
        return {"status": "empty", "message": "no uncrawled seed article", "seed_count": len(seeds), "done_count": len(done), "finished_at": utc_now()}

    arxiv_id = arxiv_id_of(seed)
    started_at = utc_now()
    pack = build_arxiv_evidence_pack(seed, timeout_sec=args.timeout_sec, user_agent=args.user_agent)
    row = {
        "arxiv_id": arxiv_id,
        "title": seed.get("title"),
        "url": seed.get("url"),
        "source_id": seed.get("source_id"),
        "source_name": seed.get("source_name"),
        "recrawled_at": started_at,
        "evidence_pack": pack,
    }
    append_jsonl(args.output_path, row)
    status = str(pack.get("status") or "unknown")
    quality = pack.get("quality_checks") if isinstance(pack.get("quality_checks"), dict) else {}
    result = {
        "status": "ok" if status == "ok" else "evidence_failed",
        "arxiv_id": arxiv_id,
        "title": seed.get("title"),
        "evidence_status": status,
        "is_trusted": bool(quality.get("is_trusted")),
        "finished_at": utc_now(),
    }
    args.state_path.parent.mkdir(parents=True, exist_ok=True)
    args.state_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Continuously crawl arXiv evidence packs from seed articles.")
    parser.add_argument("--seed-path", type=Path, default=DEFAULT_SEED_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument("--sleep-sec", type=float, default=120.0)
    parser.add_argument("--empty-sleep-sec", type=float, default=900.0)
    parser.add_argument("--max-articles", type=int, default=0, help="0 means run until the seed queue is empty.")
    parser.add_argument("--forever", action="store_true", help="Keep waiting for new seeds after the current queue is empty.")
    parser.add_argument("--user-agent", default="factor-study-paper-bot/3.0-continuous-evidence-crawl")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        dest="retry_failed",
        help="Retry previously failed articles. By default failed articles are skipped.",
    )
    parser.set_defaults(retry_failed=False)
    args = parser.parse_args()

    processed = 0
    while args.max_articles <= 0 or processed < args.max_articles:
        result = crawl_one(args)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if result.get("status") == "empty":
            if not args.forever:
                break
            time.sleep(args.empty_sleep_sec)
            continue
        processed += 1
        if args.sleep_sec > 0 and (args.max_articles <= 0 or processed < args.max_articles):
            time.sleep(args.sleep_sec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())