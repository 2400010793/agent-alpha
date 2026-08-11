from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_alpha.llm.client import LLMClient
from agent_alpha.llm.prompt_runner import load_prompt, run_json_prompt


def run_runtime_agent(
    *,
    client: LLMClient,
    system_prompt: str | Path,
    payload: dict[str, Any],
    task_name: str = "runtime_agent",
    audit_log_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run one LLM-backed runtime agent.
    """
    prompt_text = load_prompt(system_prompt) if str(system_prompt).endswith((".md", ".txt")) else str(system_prompt)
    return run_json_prompt(
        client,
        system_prompt=prompt_text,
        user_payload=json.dumps(payload, ensure_ascii=False, default=str),
        task_name=task_name,
        audit_log_dir=audit_log_dir,
    )


__all__ = ["run_runtime_agent"]