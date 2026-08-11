from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.io.config import load_config
from src.io.http import fetch_entries_for_source


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe one configured source without writing digest outputs.")
    parser.add_argument("--source-id", required=True, help="Source id in config/sources.yaml")
    parser.add_argument("--config", default=str(ROOT / "config" / "sources.yaml"))
    parser.add_argument("--timeout-sec", type=int, default=20)
    parser.add_argument("--max-items", type=int, default=5)
    parser.add_argument("--max-age-days", type=int, default=None, help="Override configured source/default max_age_days.")
    parser.add_argument("--fetch-month", default="", help="Fetch one arXiv submitted month, formatted as YYYYMM.")
    parser.add_argument("--user-agent", default="factor-study-paper-bot/1.0")
    args = parser.parse_args()

    defaults, sources = load_config(Path(args.config))
    source = next((src for src in sources if src.source_id == args.source_id), None)
    if source is None:
        print(json.dumps({"status": "failed", "error": f"source not found: {args.source_id}"}, ensure_ascii=False, indent=2))
        return 2
    max_age_days = args.max_age_days if args.max_age_days is not None else (source.max_age_days if source.max_age_days is not None else int(defaults.get("max_age_days", 0)))

    try:
        entries = fetch_entries_for_source(
            source,
            timeout_sec=args.timeout_sec,
            user_agent=args.user_agent,
            max_items=args.max_items,
            fetch_month=str(args.fetch_month).strip(),
            fetch_now=datetime.now(timezone.utc),
            max_age_days=max_age_days,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "source_id": source.source_id,
                    "url": source.url,
                    "use_proxy": source.use_proxy,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "status": "ok",
                "source_id": source.source_id,
                "url": source.url,
                "use_proxy": source.use_proxy,
                "max_age_days": max_age_days,
                "fetch_month": str(args.fetch_month).strip() or None,
                "entries": len(entries),
                "sample": entries[: args.max_items],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())