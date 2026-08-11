from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from src.io.config import SourceConfig
from src.io.http import fetch_entries_for_source


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data" / "arxiv_seed_articles_api_2y.jsonl"
DEFAULT_STATUS = ROOT / "data" / "arxiv_seed_articles_api_2y.status.json"

ARXIV_SOURCES: Tuple[SourceConfig, ...] = (
    SourceConfig("arxiv_qf", "rss", "paper", "arXiv q-fin", "https://rss.arxiv.org/rss/q-fin", True, use_proxy=False),
    SourceConfig("arxiv_stat_ml", "rss", "paper", "arXiv stat.ML", "https://rss.arxiv.org/rss/stat.ML", True, use_proxy=False),
    SourceConfig("arxiv_econ_em", "rss", "paper", "arXiv econ.EM (Econometrics)", "https://rss.arxiv.org/rss/econ.EM", True, use_proxy=False),
)


def iter_months(start: str, end: str) -> Iterable[str]:
    year = int(start[:4])
    month = int(start[4:])
    end_year = int(end[:4])
    end_month = int(end[4:])
    while (year, month) <= (end_year, end_month):
        yield f"{year:04d}{month:02d}"
        month += 1
        if month == 13:
            year += 1
            month = 1


def default_start_month(now: datetime) -> str:
    month_index = now.year * 12 + now.month - 24
    year = month_index // 12
    month = month_index % 12
    if month == 0:
        year -= 1
        month = 12
    return f"{year:04d}{month:02d}"


def load_existing(path: Path) -> Dict[str, Dict[str, object]]:
    rows: Dict[str, Dict[str, object]] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        arxiv_id = str(row.get("arxiv_id") or "").strip()
        if arxiv_id:
            rows[arxiv_id] = row
    return rows


def load_status(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"completed": [], "errors": []}
    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl(path: Path, rows: Dict[str, Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = [rows[key] for key in sorted(rows)]
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in ordered), encoding="utf-8")


def save_status(path: Path, status: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl arXiv API month-by-month for the last two years.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--status", default=str(DEFAULT_STATUS))
    parser.add_argument("--start-month", default="")
    parser.add_argument("--end-month", default=datetime.now(timezone.utc).strftime("%Y%m"))
    parser.add_argument("--max-items", type=int, default=1000)
    parser.add_argument("--timeout-sec", type=int, default=90)
    parser.add_argument("--delay-sec", type=float, default=3.5)
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    start_month = args.start_month or default_start_month(now)
    output_path = Path(args.output)
    status_path = Path(args.status)
    rows = load_existing(output_path)
    status = load_status(status_path)
    completed = set(status.get("completed") or [])
    errors: List[Dict[str, object]] = list(status.get("errors") or [])

    for month in iter_months(start_month, args.end_month):
        for source in ARXIV_SOURCES:
            task_key = f"{source.source_id}:{month}"
            if task_key in completed:
                continue
            try:
                entries = fetch_entries_for_source(
                    source,
                    timeout_sec=args.timeout_sec,
                    user_agent="factor-study-paper-bot/1.0 (mailto:research@example.invalid)",
                    max_items=args.max_items,
                    fetch_month=month,
                    fetch_now=now,
                    max_age_days=730,
                )
            except Exception as exc:
                error = {"task": task_key, "error_type": type(exc).__name__, "error": str(exc), "ts": datetime.now(timezone.utc).isoformat()}
                errors.append(error)
                status.update({"completed": sorted(completed), "errors": errors, "rows": len(rows), "last_error": error})
                save_status(status_path, status)
                write_jsonl(output_path, rows)
                print(json.dumps({"status": "error", **error, "rows": len(rows)}, ensure_ascii=False), file=sys.stderr)
                if args.stop_on_error:
                    return 1
                continue

            added = 0
            for entry in entries:
                url = str(entry.get("url") or "")
                arxiv_id = url.rstrip("/").split("/")[-1].split("v")[0]
                if not arxiv_id or arxiv_id in rows:
                    continue
                rows[arxiv_id] = {
                    "arxiv_id": arxiv_id,
                    "title": str(entry.get("title") or "").strip(),
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                    "summary": str(entry.get("summary") or "").strip(),
                    "published": str(entry.get("published") or "").strip(),
                    "source_id": source.source_id,
                    "source_name": source.source_name,
                }
                added += 1
            completed.add(task_key)
            status.update({"completed": sorted(completed), "errors": errors, "rows": len(rows), "last_success": task_key})
            save_status(status_path, status)
            write_jsonl(output_path, rows)
            print(json.dumps({"status": "ok", "task": task_key, "entries": len(entries), "added": added, "rows": len(rows)}, ensure_ascii=False))
            if args.delay_sec > 0:
                time.sleep(args.delay_sec)

    status.update({"completed": sorted(completed), "errors": errors, "rows": len(rows), "finished_at": datetime.now(timezone.utc).isoformat()})
    save_status(status_path, status)
    write_jsonl(output_path, rows)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())