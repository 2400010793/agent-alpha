#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Set

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

DEFAULT_ANALYSIS_ARCHIVE = ROOT / "data" / "opinion_analysis_archive.jsonl"
DEFAULT_EVIDENCE_ARCHIVE = ROOT / "data" / "arxiv_evidence_archive.jsonl"
DEFAULT_RUNTIME_EVIDENCE = ROOT / "data" / "runtime" / "three_ai_hourly_current_evidence.jsonl"
DEFAULT_STATE_PATH = ROOT / "data" / "runtime" / "three_ai_hourly_state.json"
DEFAULT_ATTEMPTS_PATH = ROOT / "data" / "runtime" / "three_ai_hourly_attempts.jsonl"
DEFAULT_LOG_PATH = ROOT / "logs" / "three_ai_hourly_once.log"
DEFAULT_READING_CACHE_DIR = ROOT / "data" / "runtime" / "three_ai_reading_cache"
DEFAULT_READING_CHUNK_CACHE_DIR = ROOT / "data" / "runtime" / "three_ai_reading_chunk_cache"
DEFAULT_OPINION_CACHE_DIR = ROOT / "data" / "runtime" / "three_ai_opinion_cache"


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
            item = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps({"warning": "skip_bad_jsonl", "path": str(path), "line": line_no}, ensure_ascii=False), flush=True)
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def append_jsonl(path: Path, row: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: Iterable[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def article_id(row: Dict[str, object]) -> str:
    pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
    return str(row.get("arxiv_id") or pack.get("arxiv_id") or "").strip()


def article_title(row: Dict[str, object]) -> str:
    return str(row.get("title") or row.get("resolved_title") or "").strip()


def processed_keys(analysis_rows: Iterable[Dict[str, object]]) -> Set[str]:
    keys: Set[str] = set()
    for row in analysis_rows:
        pipeline = str(row.get("analysis_pipeline") or "")
        if "three-ai" not in pipeline:
            continue
        arxiv_id = article_id(row).lower()
        title = article_title(row).lower()
        if arxiv_id:
            keys.add(f"id:{arxiv_id}")
        if title:
            keys.add(f"title:{title}")
    return keys


def attempted_keys(attempt_rows: Iterable[Dict[str, object]]) -> Set[str]:
    keys: Set[str] = set()
    for row in attempt_rows:
        if row.get("status") == "rate_limited":
            retry_after = str(row.get("retry_after") or "")
            try:
                due = datetime.fromisoformat(retry_after.replace("Z", "+00:00"))
            except ValueError:
                due = None
            if due is not None and due <= datetime.now(timezone.utc):
                # The backoff window has elapsed; make this article eligible
                # for the next timer invocation.
                continue
        arxiv_id = article_id(row).lower()
        title = article_title(row).lower()
        if arxiv_id:
            keys.add(f"id:{arxiv_id}")
        if title:
            keys.add(f"title:{title}")
    return keys


def seed_key(row: Dict[str, object]) -> str:
    arxiv_id = article_id(row).lower()
    if arxiv_id:
        return f"id:{arxiv_id}"
    return f"title:{article_title(row).lower()}"


def select_next_evidence(evidence_rows: Iterable[Dict[str, object]], done: Set[str]) -> Dict[str, object] | None:
    latest_by_id: Dict[str, Dict[str, object]] = {}
    no_id_rows: List[Dict[str, object]] = []
    for row in evidence_rows:
        arxiv_id = article_id(row).lower()
        if arxiv_id:
            latest_by_id[arxiv_id] = row
        else:
            no_id_rows.append(row)
    candidates = list(latest_by_id.values()) + no_id_rows
    for row in candidates:
        pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
        quality = pack.get("quality_checks") if isinstance(pack.get("quality_checks"), dict) else {}
        if pack.get("status") != "ok" or not quality.get("is_trusted"):
            continue
        title = article_title(row)
        if not title:
            continue
        key = seed_key(row)
        if key and key not in done and f"title:{title.lower()}" not in done:
            return row
    return None


def run_command(command: List[str], *, env: Dict[str, str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"[{utc_now()}] RUN {' '.join(command)}\n")
        log.flush()
        subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)


def build_env(args: argparse.Namespace) -> Dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PAPER_READING_LLM_MODEL", args.model)
    env.setdefault("PAPER_OPINION_LLM_MODEL", args.model)
    env.setdefault("PAPER_READING_LLM_KEY_ENV", args.reading_key_env)
    env.setdefault("PAPER_OPINION_LLM_KEY_ENV", args.opinion_key_env)
    env.setdefault("PAPER_THREE_AI_TIMEOUT_SEC", str(args.timeout_sec))
    return env


def run_once(args: argparse.Namespace) -> Dict[str, object]:
    evidence_rows = read_jsonl(args.evidence_archive)
    if args.only_opinion:
        source = Path(args.reading_note_source)
        if not source.is_absolute():
            source = ROOT / source
        cached = json.loads(source.read_text(encoding="utf-8"))
        cached_id = str(cached.get("arxiv_id") or "")
        evidence_row = next((item for item in evidence_rows if article_id(item) == cached_id), None)
        if evidence_row is None:
            evidence_row = {"arxiv_id": cached_id, "title": cached.get("title"), "url": cached.get("url"), "evidence_pack": cached.get("llm_input_evidence_pack_v2") or cached.get("llm_input_evidence_pack") or {}}
        write_jsonl(args.runtime_evidence_path, [evidence_row])
    else:
        done = processed_keys(read_jsonl(args.analysis_archive)) | attempted_keys(read_jsonl(args.attempts_path))
        evidence_row = select_next_evidence(evidence_rows, done)
    if evidence_row is None:
        return {"status": "empty", "message": "no unprocessed trusted evidence row", "evidence_count": len(evidence_rows), "processed_count": len(done), "finished_at": utc_now()}

    write_jsonl(args.runtime_evidence_path, [evidence_row])
    pack = evidence_row.get("evidence_pack") if isinstance(evidence_row.get("evidence_pack"), dict) else {}
    status = str(pack.get("status") or "unknown")
    quality = pack.get("quality_checks") if isinstance(pack.get("quality_checks"), dict) else {}
    if status != "ok" or not quality.get("is_trusted"):
        result = {
            "status": "evidence_untrusted",
            "arxiv_id": evidence_row.get("arxiv_id"),
            "title": evidence_row.get("title"),
            "evidence_status": status,
            "quality_checks": quality,
            "finished_at": utc_now(),
        }
        append_jsonl(args.attempts_path, result)
        args.state_path.parent.mkdir(parents=True, exist_ok=True)
        args.state_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    env = build_env(args)
    command = [
        sys.executable,
        "-m",
        "src.llm.three_ai.cli",
        "--project-root",
        str(ROOT),
        "--evidence-archive",
        str(args.runtime_evidence_path.relative_to(ROOT)),
        "--arxiv-id",
        str(evidence_row.get("arxiv_id") or ""),
        "--reading-model",
        args.model,
        "--opinion-model",
        args.model,
        "--reading-key-env",
        args.reading_key_env,
        "--opinion-key-env",
        args.opinion_key_env,
        "--timeout-sec",
        str(args.timeout_sec),
        "--analysis-archive",
        str(args.analysis_archive),
        "--reading-note-cache-dir",
        str(args.reading_cache_dir),
        "--reading-chunk-cache-dir",
        str(args.reading_chunk_cache_dir),
        "--opinion-cache-dir",
        str(args.opinion_cache_dir),
    ]
    if args.only_opinion:
        command.extend(["--only-opinion", "--reading-note-source", str(args.reading_note_source)])
    try:
        run_command(command, env=env, log_path=args.log_path)
        if args.render:
            run_command([sys.executable, "-m", "src.render.opinion_digest"], env=env, log_path=args.log_path)
    except subprocess.CalledProcessError as exc:
        log_tail = args.log_path.read_text(encoding="utf-8", errors="replace")[-16000:]
        rate_limited = "HTTP 429" in log_tail or "Too Many Requests" in log_tail
        result = {
            "status": "rate_limited" if rate_limited else "three_ai_failed",
            "arxiv_id": evidence_row.get("arxiv_id"),
            "title": evidence_row.get("title"),
            "returncode": exc.returncode,
            "model": args.model,
            "finished_at": utc_now(),
        }
        if rate_limited:
            result["retry_after"] = datetime.fromtimestamp(time.time() + 3 * 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        append_jsonl(args.attempts_path, result)
        args.state_path.parent.mkdir(parents=True, exist_ok=True)
        args.state_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        # A single article failure is recorded and skipped. Rate-limited
        # articles become eligible again after the three-hour backoff.
        return result

    result = {
        "status": "ok",
        "arxiv_id": evidence_row.get("arxiv_id"),
        "title": evidence_row.get("title"),
        "model": args.model,
        "runtime_evidence_path": str(args.runtime_evidence_path),
        "analysis_archive": str(args.analysis_archive),
        "finished_at": utc_now(),
    }
    append_jsonl(args.attempts_path, result)
    args.state_path.parent.mkdir(parents=True, exist_ok=True)
    args.state_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run crawled arXiv articles through the Paper Opinion Digest.")
    parser.add_argument("--analysis-archive", type=Path, default=DEFAULT_ANALYSIS_ARCHIVE)
    parser.add_argument("--evidence-archive", type=Path, default=DEFAULT_EVIDENCE_ARCHIVE)
    parser.add_argument("--only-opinion", action="store_true", help="run only opinion/idea generation using a cached reading note")
    parser.add_argument("--reading-note-source", default="data/latest_three_ai_result.json")
    parser.add_argument("--runtime-evidence-path", type=Path, default=DEFAULT_RUNTIME_EVIDENCE)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--attempts-path", type=Path, default=DEFAULT_ATTEMPTS_PATH)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--reading-cache-dir", type=Path, default=DEFAULT_READING_CACHE_DIR)
    parser.add_argument("--reading-chunk-cache-dir", type=Path, default=DEFAULT_READING_CHUNK_CACHE_DIR)
    parser.add_argument("--opinion-cache-dir", type=Path, default=DEFAULT_OPINION_CACHE_DIR)
    parser.add_argument("--model", default=os.environ.get("PAPER_THREE_AI_HOURLY_MODEL", "gpt-4o"))
    parser.add_argument("--reading-key-env", default=os.environ.get("PAPER_READING_LLM_KEY_ENV", "PAPER_LLM_API_KEY2"))
    parser.add_argument("--factor-key-env", dest="opinion_key_env", default=os.environ.get("PAPER_OPINION_LLM_KEY_ENV", "PAPER_LLM_API_KEY"))
    parser.add_argument("--timeout-sec", type=int, default=int(os.environ.get("PAPER_THREE_AI_TIMEOUT_SEC", "300")))
    parser.add_argument("--no-render", action="store_false", dest="render")
    parser.set_defaults(render=True)
    args = parser.parse_args()

    started = time.time()
    result = run_once(args)
    result["elapsed_sec"] = round(time.time() - started, 1)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"ok", "empty", "evidence_untrusted", "three_ai_failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
