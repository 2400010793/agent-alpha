"""new2-local HF agent prompt loading.

The fusion model performs mechanism classification in the same call as article
analysis. This module only supplies the agent definitions and prompts.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "hf_mechanism_agents.json"
PROMPT_ROOT = ROOT / "prompts" / "hf"

def load_agent_config() -> Dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def build_agent_prompt(agent_id: str, input_text: str = "") -> str:
    config = load_agent_config()["agents"]
    agent = config[agent_id]
    prompt_path = ROOT / str(agent.get("prompt", ""))
    shared_path = PROMPT_ROOT / "_shared_agent_contract.md"
    shared = shared_path.read_text(encoding="utf-8") if shared_path.exists() else ""
    if prompt_path.exists():
        return (prompt_path.read_text(encoding="utf-8") + shared).replace("{{INPUT_TEXT}}", input_text)
    return "\n".join([
        f"你是 new2 的高频机制 agent：{agent_id}（{agent['name']}）。",
        f"只允许使用字段：{json.dumps(agent['fields'], ensure_ascii=False)}。",
        "只输出 FactorCandidate JSON，不写 Python；只使用当前或历史数据。",
    ])


def build_all_agent_prompts(input_text: str = "") -> Dict[str, str]:
    return {agent_id: build_agent_prompt(agent_id, input_text) for agent_id in load_agent_config()["agents"]}
