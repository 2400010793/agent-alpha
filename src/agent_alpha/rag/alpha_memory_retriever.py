from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_alpha.config import project_path
from agent_alpha.factors.factor_store import DEFAULT_FACTOR_REGISTRY_PATH, load_factor_records
from agent_alpha.library.alpha_library import load_alpha_records


DEFAULT_CANDIDATE_SOURCES = (
    "outputs/manual_mutation_backtest/manual_mutation_candidates.json",
    "outputs/manual_mutation_round2/manual_mutation_round2_candidates.json",
    "outputs/factor_lineage_report/factor_and_signal_lineage_report.json",
)


def _as_strings(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).casefold()


def _read_json(path: str | Path) -> Any:
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = project_path(str(file_path))
    if not file_path.exists():
        return None
    return json.loads(file_path.read_text(encoding="utf-8"))


def _candidate_records_from_payload(payload: Any, *, source_path: str) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, dict) and isinstance(payload.get("factors"), list):
        records = payload["factors"]
    elif isinstance(payload, dict):
        records = payload.get("factor_candidates", payload.get("candidates", []))
    elif isinstance(payload, list):
        records = payload
    else:
        records = []
    out: list[dict[str, Any]] = []
    for record in records:
        if isinstance(record, dict):
            payload_record = dict(record)
            payload_record.setdefault("_source_path", source_path)
            out.append(payload_record)
    return out


def load_alpha_memory_candidates(
    *,
    factor_registry_path: str | Path = DEFAULT_FACTOR_REGISTRY_PATH,
    candidate_sources: list[str | Path] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    records.extend(load_factor_records(factor_registry_path, limit=500))
    records.extend(load_alpha_records(limit=500))
    for source in candidate_sources or list(DEFAULT_CANDIDATE_SOURCES):
        records.extend(_candidate_records_from_payload(_read_json(source), source_path=str(source)))
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = str(record.get("factor_id") or record.get("name") or record.get("factor_name") or record.get("alpha_id") or _text(record)[:120])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _record_score(signal: dict[str, Any], record: dict[str, Any]) -> tuple[float, list[str]]:
    signal_tags = set(_as_strings(signal.get("hf_mechanism_tags")))
    signal_fields = set(_as_strings(signal.get("candidate_fields")))
    signal_terms = set(_text({key: signal.get(key) for key in ("signal_name", "market_intuition", "hypothesis")}).split())
    record_tags = set(_as_strings(record.get("mechanism_tags") or record.get("hf_mechanism_tags")))
    record_fields = set(_as_strings(record.get("fields")))
    record_text = _text(record)
    reasons: list[str] = []
    score = 0.0
    tag_overlap = signal_tags & record_tags
    field_overlap = signal_fields & record_fields
    if tag_overlap:
        score += 3.0 * len(tag_overlap)
        reasons.append(f"tag_overlap:{','.join(sorted(tag_overlap))}")
    if field_overlap:
        score += 2.0 * len(field_overlap)
        reasons.append(f"field_overlap:{','.join(sorted(field_overlap))}")
    matched_terms = sorted(term for term in signal_terms if len(term) >= 5 and term in record_text)[:5]
    if matched_terms:
        score += 0.4 * len(matched_terms)
        reasons.append(f"text_overlap:{','.join(matched_terms)}")
    metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else record
    for key in ("daily_rankic_mean", "daily_rankic", "global_rankic_mean", "global_rankic", "rankic"):
        try:
            value = abs(float(metrics.get(key)))
        except (AttributeError, TypeError, ValueError):
            continue
        score += min(value, 1.0)
        reasons.append(f"metric:{key}")
        break
    return score, reasons


def search_similar_alphas(
    signal: dict[str, Any],
    *,
    limit: int = 8,
    factor_registry_path: str | Path = DEFAULT_FACTOR_REGISTRY_PATH,
    candidate_sources: list[str | Path] | None = None,
) -> dict[str, Any]:
    scored: list[tuple[float, dict[str, Any], list[str]]] = []
    for record in load_alpha_memory_candidates(factor_registry_path=factor_registry_path, candidate_sources=candidate_sources):
        score, reasons = _record_score(signal, record)
        if score <= 0:
            continue
        scored.append((score, record, reasons))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("factor_id") or item[1].get("name") or "")))
    similar = []
    for score, record, reasons in scored[: max(1, limit)]:
        similar.append(
            {
                "factor_id": record.get("factor_id") or record.get("name") or record.get("factor_name") or record.get("alpha_id"),
                "name": record.get("name") or record.get("factor_name"),
                "fields": record.get("fields", []),
                "windows": record.get("windows", []),
                "mechanism_tags": record.get("mechanism_tags") or record.get("hf_mechanism_tags") or [],
                "prefix_expression": record.get("prefix_expression"),
                "metrics": record.get("metrics", {}),
                "source_signal_id": record.get("source_signal_id", ""),
                "source_path": record.get("_source_path", ""),
                "score": round(score, 4),
                "reasons": reasons,
            }
        )
    return {"similar_factors": similar, "similar_factor_count": len(similar)}


__all__ = ["load_alpha_memory_candidates", "search_similar_alphas"]