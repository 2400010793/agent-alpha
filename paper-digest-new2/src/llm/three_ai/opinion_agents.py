"""Parallel, same-level opinion-agent prompt definitions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "opinion_agents.json"
SHARED_PATH = ROOT / "prompts" / "opinion" / "_shared_opinion_contract.md"


def load_opinion_agent_config() -> Dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def build_opinion_agent_prompt(agent_id: str, input_text: str = "") -> str:
    agent = load_opinion_agent_config()["agents"][agent_id]
    path = ROOT / str(agent["prompt"])
    specific = path.read_text(encoding="utf-8") if path.exists() else ""
    shared = SHARED_PATH.read_text(encoding="utf-8") if SHARED_PATH.exists() else ""
    return (specific + "\n" + shared).replace("{{INPUT_TEXT}}", input_text)
