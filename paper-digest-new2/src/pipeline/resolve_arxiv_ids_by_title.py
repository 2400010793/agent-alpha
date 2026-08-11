from __future__ import annotations

import argparse
import difflib
import json
import re
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from src.arxiv.ids import _extract_arxiv_id
from src.io.feed import parse_rss_or_atom
from src.io.http import fetch_url


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data" / "arxiv_seed_articles_from_new_daily_all.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "arxiv_seed_articles_from_new_daily_all_resolved.jsonl"
DEFAULT_STATUS = ROOT / "data" / "arxiv_seed_articles_from_new_daily_all_resolved.status.json"


def normalize_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def read_jsonl(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    rows: List[Dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def extract_arxiv_id(url: str) -> str:
    return _extract_arxiv_id(url)


def query_by_title(title: str, *, timeout_sec: int, user_agent: str, max_results: int) -> List[Dict[str, str]]:
    query = f'ti:"{title}"'
    params = urllib.parse.urlencode(
        {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    payload = fetch_url(f"https://export.arxiv.org/api/query?{params}", timeout_sec=timeout_sec, user_agent=user_agent, use_proxy=False)
    return parse_rss_or_atom(payload)


def best_match(row: Dict[str, object], candidates: List[Dict[str, str]], min_score: float) -> Dict[str, object]:
    target = normalize_title(str(row.get("title") or ""))
    best: Dict[str, object] = {"status": "not_found", "score": 0.0}
    for candidate in candidates:
        candidate_title = str(candidate.get("title") or "")
        score = difflib.SequenceMatcher(None, target, normalize_title(candidate_title)).ratio()
        url = str(candidate.get("url") or "")
        arxiv_id = extract_arxiv_id(url)
        if score > float(best.get("score") or 0) and arxiv_id:
            best = {
                "status": "matched" if score >= min_score else "weak_match",
                "score": score,
                "arxiv_id": arxiv_id,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "candidate_title": candidate_title,
                "candidate_published": candidate.get("published") or "",
                "candidate_summary": candidate.get("summary") or "",
            }
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve missing arXiv IDs by exact-ish title search.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--limit", type=int, default=0, help="0 means no limit")
    parser.add_argument("--timeout-sec", type=int, default=60)
    parser.add_argument("--sleep-sec", type=float, default=3.5)
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.94)
    parser.add_argument("--user-agent", default="factor-study-paper-bot/2.0-title-resolver")
    args = parser.parse_args()

    rows = read_jsonl(args.output) if args.output.exists() else read_jsonl(args.input)
    processed = 0
    status_counts: Dict[str, int] = {}
    for index, row in enumerate(rows):
        if row.get("arxiv_id") and row.get("url"):
            continue
        if row.get("title_resolution_status") in {"matched", "not_found", "weak_match", "error"}:
            continue
        if args.limit > 0 and processed >= args.limit:
            break
        title = str(row.get("title") or "").strip()
        try:
            candidates = query_by_title(title, timeout_sec=args.timeout_sec, user_agent=args.user_agent, max_results=args.max_results)
            match = best_match(row, candidates, args.min_score)
            row["title_resolution_status"] = match.get("status")
            row["title_resolution_score"] = match.get("score")
            if match.get("status") == "matched":
                row["arxiv_id"] = match.get("arxiv_id")
                row["url"] = match.get("url")
                row["resolved_title"] = match.get("candidate_title")
                if not row.get("published"):
                    row["published"] = match.get("candidate_published")
                if not row.get("summary"):
                    row["summary"] = match.get("candidate_summary")
            elif match.get("candidate_title"):
                row["title_resolution_candidate"] = match
        except Exception as exc:
            row["title_resolution_status"] = "error"
            row["title_resolution_error"] = f"{type(exc).__name__}: {exc}"
        processed += 1
        status = str(row.get("title_resolution_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        print(json.dumps({"processed": processed, "index": index, "status": status, "title": title[:120], "arxiv_id": row.get("arxiv_id") or ""}, ensure_ascii=False), flush=True)
        write_jsonl(args.output, rows)
        args.status.write_text(
            json.dumps(
                {
                    "processed_this_run": processed,
                    "status_counts_this_run": status_counts,
                    "resolved_total": sum(1 for item in rows if item.get("arxiv_id") and item.get("url")),
                    "row_count": len(rows),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if args.sleep_sec > 0 and (args.limit <= 0 or processed < args.limit):
            time.sleep(args.sleep_sec)
    write_jsonl(args.output, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())