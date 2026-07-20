from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_alpha.memory.jsonl_store import JsonlStore


DEFAULT_FUNCTION_MEMORY_PATH = "data/memory/cog/function_memory.jsonl"
FUNCTION_MEMORY_SCHEMA_VERSION = "function_memory_v1"


def function_memory_store(path: str | Path = DEFAULT_FUNCTION_MEMORY_PATH) -> JsonlStore:
    return JsonlStore(
        path=path,
        schema_version=FUNCTION_MEMORY_SCHEMA_VERSION,
        id_field="memory_id",
        default_search_fields=("label", "function_pattern", "asl_ops", "fields", "windows", "mechanism_tags", "condition", "summary", "avoid_rule", "repair_hint"),
    )


def append_function_memory(record: dict[str, Any], path: str | Path = DEFAULT_FUNCTION_MEMORY_PATH) -> dict[str, Any]:
    return function_memory_store(path).append(dict(record))


def load_function_memory(path: str | Path = DEFAULT_FUNCTION_MEMORY_PATH, *, filters: dict[str, Any] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    return function_memory_store(path).load(filters=filters, limit=limit)


def search_function_memory(query: str = "", path: str | Path = DEFAULT_FUNCTION_MEMORY_PATH, *, filters: dict[str, Any] | None = None, limit: int = 20) -> list[dict[str, Any]]:
    return function_memory_store(path).search(query, filters=filters, limit=limit)


__all__ = ["DEFAULT_FUNCTION_MEMORY_PATH", "append_function_memory", "load_function_memory", "search_function_memory"]