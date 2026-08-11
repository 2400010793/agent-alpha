from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_alpha.factors.factor_deduper import annotate_factor_identity
from agent_alpha.memory.jsonl_store import JsonlStore


DEFAULT_FACTOR_REGISTRY_PATH = "data/factor_registry/factors.jsonl"
FACTOR_REGISTRY_SCHEMA_VERSION = "factor_registry_record_v1"


def factor_registry_store(path: str | Path = DEFAULT_FACTOR_REGISTRY_PATH) -> JsonlStore:
    return JsonlStore(
        path=path,
        schema_version=FACTOR_REGISTRY_SCHEMA_VERSION,
        id_field="factor_record_id",
        default_search_fields=("factor_id", "name", "expression", "hypothesis", "fields", "mechanism_tags", "source_signal_id", "source_paper_id"),
    )


def append_factor_record(record: dict[str, Any], path: str | Path = DEFAULT_FACTOR_REGISTRY_PATH) -> dict[str, Any]:
    payload = annotate_factor_identity(record)
    if payload.get("factor_id") and not payload.get("name"):
        payload["name"] = payload["factor_id"]
    return factor_registry_store(path).append(payload)


def load_factor_records(path: str | Path = DEFAULT_FACTOR_REGISTRY_PATH, *, filters: dict[str, Any] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    return factor_registry_store(path).load(filters=filters, limit=limit)


def search_factor_records(
    query: str = "",
    path: str | Path = DEFAULT_FACTOR_REGISTRY_PATH,
    *,
    filters: dict[str, Any] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return factor_registry_store(path).search(query, filters=filters, limit=limit)


def write_factor_candidate(path: str | Path, candidate: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")