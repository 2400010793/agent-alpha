from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_alpha.memory.jsonl_store import JsonlStore


DEFAULT_TRANSFER_MEMORY_PATH = "data/memory/cog/transfer_memory.jsonl"
TRANSFER_MEMORY_SCHEMA_VERSION = "transfer_memory_v1"


def transfer_memory_store(path: str | Path = DEFAULT_TRANSFER_MEMORY_PATH) -> JsonlStore:
    return JsonlStore(
        path=path,
        schema_version=TRANSFER_MEMORY_SCHEMA_VERSION,
        id_field="memory_id",
        default_search_fields=("label", "mutation_type", "from_pattern", "to_pattern", "mechanism_tags", "agent_name", "summary", "when_to_apply", "when_not_to_apply"),
    )


def append_transfer_memory(record: dict[str, Any], path: str | Path = DEFAULT_TRANSFER_MEMORY_PATH) -> dict[str, Any]:
    return transfer_memory_store(path).append(dict(record))


def load_transfer_memory(path: str | Path = DEFAULT_TRANSFER_MEMORY_PATH, *, filters: dict[str, Any] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    return transfer_memory_store(path).load(filters=filters, limit=limit)


def search_transfer_memory(query: str = "", path: str | Path = DEFAULT_TRANSFER_MEMORY_PATH, *, filters: dict[str, Any] | None = None, limit: int = 20) -> list[dict[str, Any]]:
    return transfer_memory_store(path).search(query, filters=filters, limit=limit)


__all__ = ["DEFAULT_TRANSFER_MEMORY_PATH", "append_transfer_memory", "load_transfer_memory", "search_transfer_memory"]