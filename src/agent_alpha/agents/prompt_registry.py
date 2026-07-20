from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_alpha.config import PROJECT_ROOT
from agent_alpha.taxonomy.hf_taxonomy import load_hf_mechanisms


@dataclass(frozen=True)
class PromptSpec:
    mechanism_id: str
    path: Path

    def read_text(self) -> str:
        return self.path.read_text(encoding="utf-8")


def load_prompt_registry() -> dict[str, PromptSpec]:
    registry: dict[str, PromptSpec] = {}
    for mechanism in load_hf_mechanisms():
        mechanism_id = str(mechanism.get("id") or "")
        prompt_path = str(mechanism.get("prompt") or "")
        if not mechanism_id or not prompt_path:
            continue
        path = Path(prompt_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        registry[mechanism_id] = PromptSpec(mechanism_id=mechanism_id, path=path)
    return registry


def prompt_paths_for_tags(tags: list[str]) -> list[Path]:
    registry = load_prompt_registry()
    return [registry[tag].path for tag in tags if tag in registry]