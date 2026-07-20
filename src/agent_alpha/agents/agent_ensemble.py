from __future__ import annotations


def merge_factor_candidates(candidates: list[dict]) -> list[dict]:
    """Merge and deduplicate factor candidates by factor_id/name/expression."""
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for item in candidates:
        key = (str(item.get("factor_id", "")), str(item.get("factor_name", "")), str(item.get("factor_expression", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out