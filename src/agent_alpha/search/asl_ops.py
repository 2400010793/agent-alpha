from __future__ import annotations

import copy
import re
from typing import Any, Iterable

from agent_alpha.factors.expression_validator import validate_factor_candidate
from agent_alpha.factors.prefix_expression import fields_from_prefix, prefix_to_expression, windows_from_prefix


WINDOWS = [10, 20, 60, 120, 300, 600]
LABEL_FIELDS = {"ret10s", "ret30s", "ret60s", "ret120s"}


def clone_prefix(prefix_expression: Any) -> Any:
    return copy.deepcopy(prefix_expression)


def stable_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_").lower()
    return slug or "candidate"


def unique_items(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def candidate_generation(candidate: dict[str, Any]) -> int:
    try:
        return int(candidate.get("generation", 0) or 0)
    except (TypeError, ValueError):
        return 0


def candidate_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("factor_id") or candidate.get("name") or "candidate")


def build_candidate(
    parent: dict[str, Any],
    prefix_expression: Any,
    *,
    suffix: str,
    parent_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    generation: int | None = None,
) -> dict[str, Any] | None:
    prefix = clone_prefix(prefix_expression)
    fields = fields_from_prefix(prefix)
    if not fields or any(field in LABEL_FIELDS for field in fields):
        return None

    base_id = stable_slug(candidate_id(parent))
    child_id = f"{base_id}_{stable_slug(suffix)}"
    child = copy.deepcopy(parent)
    child.update(
        {
            "factor_id": child_id,
            "name": child_id,
            "prefix_expression": prefix,
            "expression": prefix_to_expression(prefix),
            "fields": fields,
            "windows": windows_from_prefix(prefix),
            "parent_ids": parent_ids or [candidate_id(parent)],
            "generation": candidate_generation(parent) + 1 if generation is None else generation,
            "created_by": "asl_iterative_enhancer",
        }
    )
    if metadata:
        child.update(metadata)

    validation = validate_factor_candidate(child)
    return child if validation.ok else None


def dedupe_candidates(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        key = repr(candidate.get("prefix_expression"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique