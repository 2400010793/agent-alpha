from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_alpha.config import project_path


SENSITIVE_KEY_HINTS = ("api_key", "apikey", "token", "secret", "authorization", "bearer")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).casefold()
            if any(hint in lowered for hint in SENSITIVE_KEY_HINTS):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str) and (value.startswith("github_pat_") or value.startswith("ghp_")):
        return "[REDACTED]"
    return value


def write_audit_record(record: dict[str, Any], audit_log_dir: str | Path = "outputs/llm_audit") -> Path:
    out_dir = project_path(str(audit_log_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.json"
    payload = {"created_at": _now_iso(), **redact_secrets(record)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path