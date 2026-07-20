from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_alpha.memory.jsonl_store import JsonlStore


DEFAULT_EVALUATION_RECORDS_PATH = "data/evaluation_records/evaluations.jsonl"
EVALUATION_RECORD_SCHEMA_VERSION = "evaluation_record_v1"


def evaluation_records_store(path: str | Path = DEFAULT_EVALUATION_RECORDS_PATH) -> JsonlStore:
    return JsonlStore(
        path=path,
        schema_version=EVALUATION_RECORD_SCHEMA_VERSION,
        id_field="evaluation_record_id",
        default_search_fields=("factor_id", "run_id", "decision", "retain_status", "leakage_check", "metrics", "notes"),
    )


def append_evaluation_record(record: dict[str, Any], path: str | Path = DEFAULT_EVALUATION_RECORDS_PATH) -> dict[str, Any]:
    return evaluation_records_store(path).append(record)


def load_evaluation_records(path: str | Path = DEFAULT_EVALUATION_RECORDS_PATH, *, filters: dict[str, Any] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    return evaluation_records_store(path).load(filters=filters, limit=limit)


def search_evaluation_records(
    query: str = "",
    path: str | Path = DEFAULT_EVALUATION_RECORDS_PATH,
    *,
    filters: dict[str, Any] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return evaluation_records_store(path).search(query, filters=filters, limit=limit)