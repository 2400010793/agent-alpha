#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.arxiv.evidence_pack import build_arxiv_evidence_pack  # noqa: E402

DEFAULT_SEED_PATH = ROOT / "data" / "arxiv_seed_articles.jsonl"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "arxiv_evidence_archive.jsonl"
DEFAULT_SUMMARY_PATH = ROOT / "reports" / "arxiv_evidence_recrawl_summary.json"


def read_jsonl(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    rows: List[Dict[str, object]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            print(json.dumps({"warning": "skip_bad_jsonl", "path": str(path), "line": line_no}, ensure_ascii=False), flush=True)
    return rows


def append_jsonl(path: Path, row: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def trusted_ids_from_archive(path: Path) -> set[str]:
    trusted: set[str] = set()
    for row in read_jsonl(path):
        pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
        checks = pack.get("quality_checks") if isinstance(pack.get("quality_checks"), dict) else {}
        if pack.get("status") == "ok" and checks.get("is_trusted") is True:
            arxiv_id = str(row.get("arxiv_id") or pack.get("arxiv_id") or "").strip()
            if arxiv_id:
                trusted.add(arxiv_id)
    return trusted


def recrawl(args: argparse.Namespace) -> Dict[str, object]:
    seeds = read_jsonl(args.seed_path)
    existing = read_jsonl(args.output_path) if args.resume else []
    done_ids = set()
    for row in existing:
        arxiv_id = str(row.get("arxiv_id") or "")
        pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
        if arxiv_id and (not args.retry_failed or str(pack.get("status") or "") == "ok"):
            done_ids.add(arxiv_id)
    allowed_ids = trusted_ids_from_archive(args.filter_archive) if args.filter_archive else None
    selected = [
        row for row in seeds
        if str(row.get("arxiv_id") or "") not in done_ids
        and (allowed_ids is None or str(row.get("arxiv_id") or "") in allowed_ids)
    ]
    if args.limit > 0:
        selected = selected[: args.limit]

    status_counts: Dict[str, int] = {}
    processed = 0
    for seed in selected:
        arxiv_id = str(seed.get("arxiv_id") or "")
        started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        pack = build_arxiv_evidence_pack(seed, timeout_sec=args.timeout_sec, user_agent=args.user_agent)
        status = str(pack.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        append_jsonl(
            args.output_path,
            {
                "arxiv_id": arxiv_id,
                "title": seed.get("title"),
                "url": seed.get("url"),
                "source_id": seed.get("source_id"),
                "source_name": seed.get("source_name"),
                "recrawled_at": started_at,
                "evidence_pack": pack,
            },
        )
        processed += 1
        print(json.dumps({"processed": processed, "arxiv_id": arxiv_id, "status": status}, ensure_ascii=False), flush=True)
        if args.sleep_sec > 0 and processed < len(selected):
            time.sleep(args.sleep_sec)

    all_rows = read_jsonl(args.output_path)
    summary = {
        "seed_count": len(seeds),
        "already_done_before_run": len(done_ids),
        "processed_this_run": processed,
        "archive_count_after_run": len(all_rows),
        "status_counts_this_run": status_counts,
        "output_path": str(args.output_path),
    }
    args.summary_path.parent.mkdir(parents=True, exist_ok=True)
    args.summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Recrawl clean arXiv TeX evidence packs from seed articles.")
    parser.add_argument("--seed-path", type=Path, default=DEFAULT_SEED_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--summary-path", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--filter-archive", type=Path, default=None, help="Only recrawl trusted arXiv IDs found in this evidence archive.")
    parser.add_argument("--limit", type=int, default=0, help="0 means no limit")
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument("--sleep-sec", type=float, default=120.0)
    parser.add_argument("--user-agent", default="factor-study-paper-bot/2.0-clean-recrawl")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        dest="retry_failed",
        help="Retry previously failed articles. By default failed articles are skipped.",
    )
    parser.set_defaults(retry_failed=False)
    args = parser.parse_args()
    summary = recrawl(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())