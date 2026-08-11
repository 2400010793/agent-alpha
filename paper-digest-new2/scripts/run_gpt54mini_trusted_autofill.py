#!/usr/bin/env python3
"""Keep parsing all trusted downloaded articles with bounded concurrency."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "bin" / "python"


def jsonl_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def trusted_ids(path: Path) -> list[str]:
    ids = set()
    for row in jsonl_rows(path):
        pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
        checks = pack.get("quality_checks") if isinstance(pack.get("quality_checks"), dict) else {}
        if pack.get("status") == "ok" and checks.get("is_trusted") is True:
            article_id = str(row.get("arxiv_id") or pack.get("arxiv_id") or "").strip()
            if article_id:
                ids.add(article_id)
    return sorted(ids)


def result_ids() -> set[str]:
    ids = set()
    for path in (ROOT / "data" / "runtime").glob("gpt54mini_*/**/result.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(row, dict) and row.get("status") in {"ok", "filtered"} and row.get("arxiv_id"):
            ids.add(str(row["arxiv_id"]))
    return ids


def process_args(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


def active_cli_count() -> int:
    return sum("src.llm.three_ai.cli" in process_args(int(entry.name)) for entry in Path("/proc").iterdir() if entry.name.isdigit())


def active_ids(launch_path: Path) -> set[str]:
    ids = set()
    lines = launch_path.read_text(encoding="utf-8").splitlines() if launch_path.exists() else []
    for line in lines:
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        article_id, pid_text = parts
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if "src.llm.three_ai.cli" in process_args(pid):
            ids.add(article_id)
    return ids


def active_ids_from_all_runs(exclude: Path) -> set[str]:
    ids = set()
    for launch_path in (ROOT / "data" / "runtime").glob("gpt54mini_*/launches.tsv"):
        if launch_path == exclude:
            continue
        ids.update(active_ids(launch_path))
    return ids


def launch(article_id: str, args: argparse.Namespace, run_root: Path, launches: Path) -> None:
    article_root = run_root / article_id
    article_root.mkdir(parents=True, exist_ok=True)
    log_path = ROOT / "logs" / f"gpt54mini_autofill_{article_id}.log"
    command = [
        str(PYTHON), "-m", "src.llm.three_ai.cli", "--project-root", str(ROOT),
        "--evidence-archive", str(args.evidence_archive), "--arxiv-id", article_id,
        "--reading-model", args.model, "--opinion-model", args.model,
        "--copilot-bin", args.copilot_bin, "--timeout-sec", str(args.timeout_sec), "--chunked-reading",
        "--reading-note-cache-dir", str(article_root / "reading_cache"),
        "--reading-chunk-cache-dir", str(article_root / "reading_chunk_cache"),
        "--opinion-cache-dir", str(article_root / "opinion_cache"),
        "--analysis-archive", str(article_root / "analysis.jsonl"), "--output", str(article_root / "result.json"),
    ]
    env = os.environ.copy()
    env.update({"COPILOT_P_BIN": args.copilot_bin, "PAPER_COPILOT_AIC_LOG": str(args.aic_log), "PAPER_LLM_ARTICLE_ID": article_id, "PAPER_AIC_ONLY": "0"})
    with log_path.open("ab") as log_handle:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log_handle, stderr=subprocess.STDOUT, start_new_session=True)
    with launches.open("a", encoding="utf-8") as handle:
        handle.write(f"{article_id}\t{process.pid}\n")
        handle.flush()
    print(json.dumps({"status": "launched", "arxiv_id": article_id, "pid": process.pid}, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-archive", default="data/arxiv_tex_evidence_archive.jsonl")
    parser.add_argument("--run-root", default="data/runtime/gpt54mini_autofill")
    parser.add_argument("--aic-log", default="data/runtime/gpt54mini_autofill/aic_logs/copilot_p_aic.jsonl")
    parser.add_argument("--copilot-bin", default="/home/gaozh/bin/copilot-p")
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--timeout-sec", type=int, default=900)
    parser.add_argument("--max-concurrency", type=int, default=60)
    parser.add_argument("--poll-sec", type=float, default=15)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    evidence_archive = Path(args.evidence_archive)
    if not evidence_archive.is_absolute():
        evidence_archive = ROOT / evidence_archive
    args.evidence_archive = str(evidence_archive)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = ROOT / run_root
    args.aic_log = Path(args.aic_log)
    if not args.aic_log.is_absolute():
        args.aic_log = ROOT / args.aic_log
    run_root.mkdir(parents=True, exist_ok=True)
    args.aic_log.parent.mkdir(parents=True, exist_ok=True)
    launches = run_root / "launches.tsv"
    with (run_root / ".manager.lock").open("w") as lock_handle:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("another autofill manager is already running")
        while True:
            trusted = trusted_ids(evidence_archive)
            trusted_set = set(trusted)
            completed = result_ids()
            active = active_ids(launches) | active_ids_from_all_runs(launches)
            capacity = max(0, args.max_concurrency - active_cli_count())
            pending = [article_id for article_id in trusted if article_id not in completed and article_id not in active]
            for article_id in pending[:capacity]:
                launch(article_id, args, run_root, launches)
            active_after = active_cli_count()
            print(json.dumps({"status": "progress", "trusted": len(trusted), "completed": len(completed & trusted_set), "active": active_after, "pending": max(0, len(pending) - capacity)}, ensure_ascii=False), flush=True)
            if args.once or not pending:
                return 0
            time.sleep(args.poll_sec)


if __name__ == "__main__":
    raise SystemExit(main())
