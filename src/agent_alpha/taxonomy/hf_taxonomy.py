from __future__ import annotations

from agent_alpha.config import load_yaml


def load_hf_mechanisms(path: str = "configs/mechanism_taxonomy.yaml") -> list[dict]:
    payload = load_yaml(path)
    return list(payload.get("mechanisms", []))