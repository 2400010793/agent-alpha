#!/usr/bin/env python3
"""Run article pipelines serially with a cooldown between completed articles."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--article-interval-sec", type=float, default=1800)
    parser.add_argument("--reading-note-cache-dir", default="data/reading_note_cache_20260723")
    parser.add_argument("--evidence-archive")
    parser.add_argument("--reading-model")
    parser.add_argument("--opinion-model")
    parser.add_argument("--reading-key-env")
    parser.add_argument("--opinion-key-env")
    parser.add_argument("--single-call-chunked-reading", action="store_true")
    parser.add_argument("--timeout-sec", type=int)
    parser.add_argument("--analysis-archive")
    parser.add_argument("--output")
    parser.add_argument("articles", nargs="+")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    for index, article_id in enumerate(args.articles):
        started = datetime.now(timezone.utc).isoformat()
        print(f"[{started}] start {article_id}", flush=True)
        command = [
            sys.executable,
            "-m",
            "src.llm.three_ai.cli",
            "--project-root",
            str(root),
            "--arxiv-id",
            article_id,
            "--call-interval-sec",
            "0",
            "--reading-note-cache-dir",
            args.reading_note_cache_dir,
        ]
        for option in (
            "evidence_archive",
            "reading_model",
            "opinion_model",
            "reading_key_env",
            "opinion_key_env",
            "timeout_sec",
            "analysis_archive",
            "output",
        ):
            value = getattr(args, option)
            if value is not None:
                command.extend([f"--{option.replace('_', '-')}", str(value)])
        if args.single_call_chunked_reading:
            command.append("--single-call-chunked-reading")
        completed = subprocess.run(command, cwd=root)
        if completed.returncode != 0:
            print(f"[{datetime.now(timezone.utc).isoformat()}] failed {article_id}", flush=True)
            return completed.returncode
        print(f"[{datetime.now(timezone.utc).isoformat()}] done {article_id}", flush=True)
        if index + 1 < len(args.articles) and args.article_interval_sec > 0:
            print(f"waiting {args.article_interval_sec:g} seconds before next article", flush=True)
            time.sleep(args.article_interval_sec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
