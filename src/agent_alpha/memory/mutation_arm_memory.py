from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_alpha.memory.jsonl_store import JsonlStore


DEFAULT_MUTATION_ARM_MEMORY_PATH = "data/memory/cog/mutation_arm_memory.jsonl"
MUTATION_ARM_MEMORY_SCHEMA_VERSION = "mutation_arm_memory_v1"


def mutation_arm_id(lineage_id: str, mutation_focus: str) -> str:
    return f"{lineage_id}:{mutation_focus}"


def mutation_arm_memory_store(path: str | Path = DEFAULT_MUTATION_ARM_MEMORY_PATH) -> JsonlStore:
    return JsonlStore(
        path=path,
        schema_version=MUTATION_ARM_MEMORY_SCHEMA_VERSION,
        id_field="event_id",
        default_search_fields=("arm_id", "lineage_id", "mutation_focus", "agent_name", "label", "summary"),
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def append_mutation_arm_event(
    record: dict[str, Any],
    path: str | Path = DEFAULT_MUTATION_ARM_MEMORY_PATH,
) -> dict[str, Any]:
    lineage_id = str(record.get("lineage_id") or "unknown_lineage")
    mutation_focus = str(record.get("mutation_focus") or "unknown_focus")
    payload = dict(record)
    payload.setdefault("arm_id", mutation_arm_id(lineage_id, mutation_focus))
    payload.setdefault("lineage_id", lineage_id)
    payload.setdefault("mutation_focus", mutation_focus)
    payload.setdefault("reward", 0.0)
    payload.setdefault("success", _safe_float(payload.get("reward"), 0.0) > 0)
    return mutation_arm_memory_store(path).append(payload)


def load_mutation_arm_events(
    path: str | Path = DEFAULT_MUTATION_ARM_MEMORY_PATH,
    *,
    filters: dict[str, Any] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    return mutation_arm_memory_store(path).load(filters=filters, limit=limit)


def load_mutation_arm_memory(path: str | Path = DEFAULT_MUTATION_ARM_MEMORY_PATH) -> dict[str, dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = {}
    for event in load_mutation_arm_events(path):
        arm_id = str(event.get("arm_id") or mutation_arm_id(str(event.get("lineage_id") or "unknown_lineage"), str(event.get("mutation_focus") or "unknown_focus")))
        current = aggregates.setdefault(
            arm_id,
            {
                "arm_id": arm_id,
                "lineage_id": str(event.get("lineage_id") or "unknown_lineage"),
                "mutation_focus": str(event.get("mutation_focus") or "unknown_focus"),
                "agent_name": str(event.get("agent_name") or ""),
                "n_trials": 0,
                "mean_reward": 0.0,
                "failure_count": 0,
                "success_count": 0,
                "last_reward": 0.0,
                "updated_at": event.get("updated_at") or event.get("created_at"),
            },
        )
        reward = _safe_float(event.get("reward"), 0.0)
        n_trials = _safe_int(current.get("n_trials"), 0)
        current["mean_reward"] = (current["mean_reward"] * n_trials + reward) / (n_trials + 1)
        current["n_trials"] = n_trials + 1
        current["last_reward"] = reward
        if bool(event.get("success")):
            current["success_count"] = _safe_int(current.get("success_count"), 0) + 1
        else:
            current["failure_count"] = _safe_int(current.get("failure_count"), 0) + 1
        current["updated_at"] = event.get("updated_at") or event.get("created_at") or current.get("updated_at")
        if event.get("agent_name"):
            current["agent_name"] = str(event.get("agent_name"))
    return aggregates


__all__ = [
    "DEFAULT_MUTATION_ARM_MEMORY_PATH",
    "append_mutation_arm_event",
    "load_mutation_arm_events",
    "load_mutation_arm_memory",
    "mutation_arm_id",
    "mutation_arm_memory_store",
]