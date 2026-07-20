from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_alpha.memory.jsonl_store import JsonlStore


DEFAULT_FEEDBACK_MEMORY_PATH = "data/feedback_memory/good_bad.jsonl"
FEEDBACK_MEMORY_SCHEMA_VERSION = "feedback_memory_record_v1"


def feedback_memory_store(path: str | Path = DEFAULT_FEEDBACK_MEMORY_PATH) -> JsonlStore:
    return JsonlStore(
        path=path,
        schema_version=FEEDBACK_MEMORY_SCHEMA_VERSION,
        id_field="feedback_id",
        default_search_fields=("factor_id", "label", "failure_type", "reusable_principle", "avoid_rule", "repair_hint", "next_topics", "summary"),
    )


def append_feedback_record(record: dict[str, Any], path: str | Path = DEFAULT_FEEDBACK_MEMORY_PATH) -> dict[str, Any]:
    payload = dict(record)
    label = str(payload.get("label") or payload.get("verdict") or "").upper()
    if label:
        if label not in {"GOOD", "BAD", "REVISE", "NEUTRAL"}:
            raise ValueError("feedback label must be GOOD, BAD, REVISE, or NEUTRAL")
        payload["label"] = label
    return feedback_memory_store(path).append(payload)


def load_feedback_records(path: str | Path = DEFAULT_FEEDBACK_MEMORY_PATH, *, filters: dict[str, Any] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    return feedback_memory_store(path).load(filters=filters, limit=limit)


def search_feedback_records(
    query: str = "",
    path: str | Path = DEFAULT_FEEDBACK_MEMORY_PATH,
    *,
    filters: dict[str, Any] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return feedback_memory_store(path).search(query, filters=filters, limit=limit)