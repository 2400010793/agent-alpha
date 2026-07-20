from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_alpha.memory.jsonl_store import JsonlStore


DEFAULT_SPECIALIST_MEMORY_DIR = "data/memory/cog/specialist_agents"
SPECIALIST_MEMORY_SCHEMA_VERSION = "specialist_agent_memory_v1"


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").casefold()
    return text or "unknown_agent"


def specialist_memory_path(agent_name: str, root: str | Path = DEFAULT_SPECIALIST_MEMORY_DIR) -> Path:
    return Path(root) / f"{_slug(agent_name)}.jsonl"


def specialist_memory_store(agent_name: str, root: str | Path = DEFAULT_SPECIALIST_MEMORY_DIR) -> JsonlStore:
    return JsonlStore(
        path=specialist_memory_path(agent_name, root),
        schema_version=SPECIALIST_MEMORY_SCHEMA_VERSION,
        id_field="memory_id",
        default_search_fields=("agent_name", "mutation_focus", "label", "summary", "avoid_rule", "repair_hint", "mechanism_tags", "fields"),
    )


def append_specialist_memory(agent_name: str, record: dict[str, Any], root: str | Path = DEFAULT_SPECIALIST_MEMORY_DIR) -> dict[str, Any]:
    payload = dict(record)
    payload.setdefault("agent_name", agent_name)
    return specialist_memory_store(agent_name, root).append(payload)


def load_specialist_memory(agent_name: str, root: str | Path = DEFAULT_SPECIALIST_MEMORY_DIR, *, limit: int | None = None) -> list[dict[str, Any]]:
    return specialist_memory_store(agent_name, root).load(limit=limit)


def search_specialist_memory(agent_name: str, query: str = "", root: str | Path = DEFAULT_SPECIALIST_MEMORY_DIR, *, limit: int = 5) -> list[dict[str, Any]]:
    return specialist_memory_store(agent_name, root).search(query, limit=limit)


__all__ = [
    "DEFAULT_SPECIALIST_MEMORY_DIR",
    "append_specialist_memory",
    "load_specialist_memory",
    "search_specialist_memory",
    "specialist_memory_path",
    "specialist_memory_store",
]