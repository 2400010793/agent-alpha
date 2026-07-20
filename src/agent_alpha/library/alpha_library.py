from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_alpha.config import load_yaml
from agent_alpha.memory.jsonl_store import JsonlStore


ALPHA_LIBRARY_SCHEMA_VERSION = "alpha_library_record_v1"


def default_alpha_library_path() -> Path:
    config = load_yaml("configs/alpha_library.yaml")
    library_dir = Path(str(config.get("library_dir", "outputs/alpha_library")))
    return library_dir / "alpha_library.jsonl"


def alpha_library_store(path: str | Path | None = None) -> JsonlStore:
    return JsonlStore(
        path=path or default_alpha_library_path(),
        schema_version=ALPHA_LIBRARY_SCHEMA_VERSION,
        id_field="alpha_id",
        default_search_fields=("alpha_id", "factor_id", "name", "status", "decision", "fields", "mechanism_tags", "metrics", "summary"),
    )


def _metric_value(record: dict[str, Any], key: str) -> float | None:
    metrics = record.get("metrics")
    source = metrics if isinstance(metrics, dict) else record
    try:
        return float(source[key])
    except (KeyError, TypeError, ValueError):
        return None


def _first_metric_value(record: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _metric_value(record, key)
        if value is not None:
            return value
    return None


def admit_alpha(record: dict) -> dict:
    """Admit an alpha after evaluation.

    This keeps admission local and deterministic; it does not run evaluation.
    """
    config = load_yaml("configs/alpha_library.yaml")
    admission = config.get("admission", {}) if isinstance(config.get("admission"), dict) else {}
    required_decision = str(admission.get("required_decision", "accept"))
    if record.get("decision") != required_decision:
        raise ValueError("only accepted alpha records can be admitted")
    rankic = _first_metric_value(record, ("rankic", "daily_rankic", "global_rankic", "daily_ic", "global_ic"))
    min_abs_rankic = admission.get("min_abs_rankic")
    if rankic is not None and min_abs_rankic is not None and abs(rankic) < float(min_abs_rankic):
        raise ValueError("alpha rankic does not meet admission threshold")
    finite_ratio = _metric_value(record, "finite_ratio")
    min_finite_ratio = admission.get("min_finite_ratio")
    if finite_ratio is not None and min_finite_ratio is not None and finite_ratio < float(min_finite_ratio):
        raise ValueError("alpha finite_ratio does not meet admission threshold")
    payload = dict(record)
    payload.setdefault("status", "admitted")
    return payload


def append_alpha_record(record: dict[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    return alpha_library_store(path).append(admit_alpha(record))


def load_alpha_records(path: str | Path | None = None, *, filters: dict[str, Any] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    return alpha_library_store(path).load(filters=filters, limit=limit)


def search_alpha_records(
    query: str = "",
    path: str | Path | None = None,
    *,
    filters: dict[str, Any] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return alpha_library_store(path).search(query, filters=filters, limit=limit)


def search_elite(query: str = "", path: str | Path | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    return search_alpha_records(query, path=path, filters={"status": "admitted"}, limit=limit)