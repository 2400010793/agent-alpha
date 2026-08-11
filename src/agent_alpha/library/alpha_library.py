from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from agent_alpha.config import load_yaml
from agent_alpha.factors.factor_deduper import annotate_factor_identity, find_duplicate_candidate
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


def build_alpha_record(candidate: dict[str, Any], review: dict[str, Any], metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build an admission payload that preserves executable factor metadata."""
    payload = dict(candidate)
    payload.update(
        {
            "factor_id": str(candidate.get("factor_id") or candidate.get("name") or review.get("factor_id") or ""),
            "name": str(candidate.get("name") or review.get("factor_name") or candidate.get("factor_id") or ""),
            "decision": review.get("decision"),
            "metrics": dict(metrics or review.get("metrics") or {}),
            "review": review,
            "failure_modes": review.get("failure_modes", []),
            "good_patterns": review.get("good_patterns", []),
            "bad_patterns": review.get("bad_patterns", []),
            "statistical_summary": review.get("statistical_summary", ""),
            "risk_summary": review.get("risk_summary", ""),
            "economic_logic_summary": review.get("economic_logic_summary", ""),
            "implementation_quality_summary": review.get("implementation_quality_summary", ""),
        }
    )
    if candidate.get("parent_ids"):
        payload["parent_ids"] = list(candidate.get("parent_ids") or [])
    if candidate.get("mutation_type"):
        payload["mutation_type"] = candidate.get("mutation_type")
    if candidate.get("specialist_agent_name"):
        payload["specialist_agent_name"] = candidate.get("specialist_agent_name")
    return payload


def admit_alpha(record: dict, *, existing_records: list[dict[str, Any]] | None = None) -> dict:
    """Admit a non-duplicate alpha once it has measured performance.

    Library admission is intentionally separate from mutation selection: an
    admitted factor remains eligible for future mutation unless the selector
    rejects it for implementation failure, duplication, or low priority.
    """
    config = load_yaml("configs/alpha_library.yaml")
    admission = config.get("admission") if isinstance(config.get("admission"), dict) else {}
    required_decision = str(admission.get("required_decision", "accept")).casefold()
    decision = str(record.get("decision") or "").casefold()
    if decision != required_decision:
        raise ValueError(f"alpha must be accepted before admission (required decision: {required_decision})")
    rankic = _first_metric_value(record, ("rankic", "daily_rankic", "global_rankic", "daily_ic", "global_ic"))
    if rankic is None:
        raise ValueError("alpha performance metric is required for admission")
    if not math.isfinite(rankic):
        raise ValueError("alpha rankic must be finite for admission")
    min_abs_rankic = float(admission.get("min_abs_rankic", 0.1))
    if abs(rankic) < min_abs_rankic:
        raise ValueError(f"alpha rankic is too weak for admission: {abs(rankic):g}<{min_abs_rankic:g}")
    finite_ratio = _first_metric_value(record, ("finite_ratio",))
    min_finite_ratio = float(admission.get("min_finite_ratio", 0.8))
    if finite_ratio is None or not math.isfinite(finite_ratio):
        raise ValueError("alpha finite_ratio is required and must be finite for admission")
    if finite_ratio < min_finite_ratio:
        raise ValueError(f"alpha finite_ratio is too low for admission: {finite_ratio:g}<{min_finite_ratio:g}")
    payload = annotate_factor_identity(record)
    payload["performance_score"] = abs(rankic)
    duplicate = find_duplicate_candidate(payload, existing_records or [])
    if duplicate.is_duplicate:
        raise ValueError(f"duplicate alpha canonical_factor_key already admitted: {duplicate.duplicate_of or duplicate.canonical_factor_key}")
    payload.setdefault("status", "admitted")
    return payload


def append_alpha_record(record: dict[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    store = alpha_library_store(path)
    return store.append(admit_alpha(record, existing_records=store.load()))


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
