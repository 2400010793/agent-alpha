from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_alpha.memory.jsonl_store import JsonlStore


DEFAULT_DEPLOYMENT_REGISTRY_PATH = "outputs/deployment_registry/deployments.jsonl"
DEPLOYMENT_REGISTRY_SCHEMA_VERSION = "deployment_registry_record_v1"


def deployment_registry_store(path: str | Path = DEFAULT_DEPLOYMENT_REGISTRY_PATH) -> JsonlStore:
    return JsonlStore(
        path=path,
        schema_version=DEPLOYMENT_REGISTRY_SCHEMA_VERSION,
        id_field="deployment_id",
        default_search_fields=("factor_id", "name", "status", "environment", "notes"),
    )


def register_deployment(record: dict[str, Any], path: str | Path = DEFAULT_DEPLOYMENT_REGISTRY_PATH) -> dict[str, Any]:
    """Register deployable alpha metadata.
    """
    payload = dict(record)
    factor_id = str(payload.get("factor_id") or payload.get("name") or "").strip()
    if not factor_id:
        raise ValueError("deployment record requires factor_id or name")
    payload["factor_id"] = factor_id
    payload.setdefault("status", "registered")
    payload.setdefault("environment", "research")
    return deployment_registry_store(path).append(payload)


def load_deployments(path: str | Path = DEFAULT_DEPLOYMENT_REGISTRY_PATH, *, limit: int | None = None) -> list[dict[str, Any]]:
    return deployment_registry_store(path).load(limit=limit)


__all__ = ["DEFAULT_DEPLOYMENT_REGISTRY_PATH", "deployment_registry_store", "load_deployments", "register_deployment"]