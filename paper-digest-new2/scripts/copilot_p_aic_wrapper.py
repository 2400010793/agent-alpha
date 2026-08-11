#!/usr/bin/env python3
"""AIC/latency wrapper for a Copilot CLI-compatible command.

The wrapper intentionally records metadata only. It never records prompts,
responses, or credentials. Token usage is recorded only when the CLI returns a
JSON object containing a ``usage`` object.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import re
from datetime import datetime, timezone
from pathlib import Path


def _env_path(name: str, default: str) -> Path:
    path = Path(os.environ.get(name, default)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _append(record: dict) -> None:
    path = _env_path("PAPER_COPILOT_AIC_LOG", "logs/copilot_p_aic_calls.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _arg_value(args: list[str], name: str) -> str:
    try:
        return args[args.index(name) + 1]
    except (ValueError, IndexError):
        return ""


def _usage(output: str) -> dict | None:
    try:
        value = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    usage = value.get("usage") if isinstance(value, dict) else None
    return usage if isinstance(usage, dict) else None


def _cli_usage(output: str) -> dict:
    """Parse the non-sensitive usage footer printed by Copilot CLI."""
    usage: dict[str, object] = {}
    credits = re.search(r"AI Credits\s+([0-9]+(?:\.[0-9]+)?)", output)
    tokens = re.search(
        r"Tokens\s+↑\s*([0-9]+(?:\.[0-9]+)?k?)"
        r"(?:\s*\([^)]*\))?\s*•\s*↓\s*([0-9]+(?:\.[0-9]+)?k?)",
        output,
    )
    if credits:
        usage["cli_ai_credits"] = float(credits.group(1))
    if tokens:
        usage["cli_tokens_up_display"] = tokens.group(1)
        usage["cli_tokens_down_display"] = tokens.group(2)
    return usage


def main() -> int:
    cli = os.environ.get("COPILOT_P_BIN", "copilot-p")
    command = [cli, *sys.argv[1:]]
    stage = os.environ.get("PAPER_LLM_STAGE", "unknown")
    article_id = os.environ.get("PAPER_LLM_ARTICLE_ID", "unknown")
    model = _arg_value(sys.argv[1:], "--model") or os.environ.get("PAPER_LLM_MODEL", "unknown")
    started = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    process = subprocess.run(command, text=True, capture_output=True, encoding="utf-8", errors="replace")
    elapsed = round(time.monotonic() - start, 3)
    output = process.stdout or ""
    cli_footer = (process.stderr or "") + "\n" + output
    usage = _usage(output)
    usage_status = "returned" if usage else "not_returned"
    cli_usage = _cli_usage(cli_footer)
    if cli_usage:
        usage = {**(usage or {}), **cli_usage}
        usage_status = "cli_footer"
    record = {
        "call_id": f"copilot-p-{time.time_ns()}",
        "stage": stage,
        "article_id": article_id,
        "model": model,
        "started_at": started,
        "elapsed_sec": elapsed,
        "status": "ok" if process.returncode == 0 else "error",
        "status_code": process.returncode,
        "usage": usage,
        "usage_status": usage_status,
        "backend": "copilot-p",
    }
    _append(record)
    sys.stdout.write(output)
    sys.stderr.write(process.stderr or "")
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
