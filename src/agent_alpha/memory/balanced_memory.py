from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime
from typing import Any


def _casefold_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).casefold()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result else default


def _parse_time(value: Any) -> float:
    text = str(value or "")
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _stable_seed(seed_text: str) -> int:
    return int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16)


def _relevance(record: dict[str, Any], query_terms: list[str]) -> float:
    if not query_terms:
        return 0.0
    haystack = _casefold_json(record)
    return sum(1.0 for term in query_terms if term in haystack) / max(1, len(query_terms))


def _quality(record: dict[str, Any]) -> float:
    label = str(record.get("label") or "").upper()
    delta = _safe_float(record.get("delta_score"), 0.0)
    mean_reward = _safe_float(record.get("mean_reward"), 0.0)
    score = delta + mean_reward
    if label == "GOOD":
        score += 0.2
    elif label == "BAD":
        score -= 0.1
    elif label == "REVISE":
        score += 0.02
    return score


def _usage_penalty(record: dict[str, Any]) -> float:
    return min(0.2, _safe_float(record.get("usage_count"), 0.0) * 0.02)


def _score(record: dict[str, Any], query_terms: list[str]) -> float:
    return _relevance(record, query_terms) + _quality(record) - _usage_penalty(record)


def _is_warning(record: dict[str, Any]) -> bool:
    label = str(record.get("label") or "").upper()
    return label == "BAD" or _safe_float(record.get("delta_score"), 0.0) < 0 or bool(record.get("failure_modes"))


def _is_positive(record: dict[str, Any]) -> bool:
    label = str(record.get("label") or "").upper()
    if label == "GOOD":
        return True
    if label == "BAD":
        return False
    return _safe_float(record.get("delta_score"), 0.0) >= 0 and not record.get("failure_modes")


def _dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for record in records:
        key = str(record.get("memory_id") or record.get("feedback_id") or json.dumps(record, sort_keys=True, ensure_ascii=False, default=str))
        if key in seen:
            continue
        seen.add(key)
        out.append(record)
    return out


def _take_ranked(records: list[dict[str, Any]], query_terms: list[str], count: int) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    return sorted(records, key=lambda record: (_score(record, query_terms), _parse_time(record.get("updated_at") or record.get("created_at"))), reverse=True)[:count]


def _take_recent(records: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    return sorted(records, key=lambda record: _parse_time(record.get("updated_at") or record.get("created_at")), reverse=True)[:count]


def _take_explore(records: list[dict[str, Any]], selected: list[dict[str, Any]], count: int, seed_text: str) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    selected_ids = {id(record) for record in selected}
    pool = [record for record in records if id(record) not in selected_ids]
    pool.sort(key=lambda record: (_safe_float(record.get("usage_count"), 0.0), _parse_time(record.get("updated_at") or record.get("created_at"))))
    if not pool:
        return []
    rng = random.Random(_stable_seed(seed_text))
    sample_pool = pool[: max(count * 4, count)]
    rng.shuffle(sample_pool)
    return sample_pool[:count]


def select_balanced_memory(
    records: list[dict[str, Any]],
    *,
    query: str = "",
    kind: str = "generic",
    limit: int = 5,
    seed_text: str = "",
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    query_terms = [term.casefold() for term in query.split() if term.strip()]
    records = [record for record in records if isinstance(record, dict)]
    if not records:
        return []
    selected: list[dict[str, Any]] = []
    positives = [record for record in records if _is_positive(record)]
    warnings = [record for record in records if _is_warning(record)]
    if kind == "function":
        selected.extend(_take_ranked(warnings, query_terms, 2))
        selected.extend(_take_ranked(positives, query_terms, 1))
    elif kind == "transfer":
        selected.extend(_take_ranked(positives, query_terms, 2))
        selected.extend(_take_ranked(warnings, query_terms, 1))
    else:
        selected.extend(_take_ranked(positives, query_terms, 2))
        selected.extend(_take_ranked(warnings, query_terms, 1))
    selected = _dedupe(selected)
    selected.extend(_take_recent([record for record in records if record not in selected], 1))
    selected = _dedupe(selected)
    selected.extend(_take_explore(records, selected, max(0, limit - len(selected)), seed_text or f"{kind}:{query}"))
    return _dedupe(selected)[:limit]


__all__ = ["select_balanced_memory"]