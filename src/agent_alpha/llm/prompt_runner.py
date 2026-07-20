from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_alpha.config import PROJECT_ROOT
from agent_alpha.llm.audit_log import write_audit_record
from agent_alpha.llm.client import LLMClient


def load_prompt(path: str | Path) -> str:
    prompt_path = Path(path)
    if not prompt_path.is_absolute():
        prompt_path = PROJECT_ROOT / prompt_path
    return prompt_path.read_text(encoding="utf-8")


def run_json_prompt(
    client: LLMClient,
    *,
    system_prompt: str,
    user_payload: str,
    task_name: str,
    audit_log_dir: str | Path | None = None,
) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_payload},
    ]
    response = client.complete_json(messages)
    if audit_log_dir:
        write_audit_record(
            {
                "task_name": task_name,
                "model": getattr(client.settings, "model", ""),
                "messages": messages,
                "response": response,
            },
            audit_log_dir=audit_log_dir,
        )
    return response