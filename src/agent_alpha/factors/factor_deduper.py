from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_alpha.factors.factor_identity import canonical_factor_key, canonical_factor_metadata


@dataclass(frozen=True)
class DuplicateCheck:
    is_duplicate: bool
    canonical_factor_key: str
    duplicate_of: str = ""
    reason: str = ""


def find_duplicate_candidate(candidate: dict[str, Any], records: list[dict[str, Any]]) -> DuplicateCheck:
    key = canonical_factor_key(candidate)
    for record in records:
        record_key = str(record.get("canonical_factor_key") or "") or canonical_factor_key(record)
        if record_key == key:
            duplicate_of = str(record.get("factor_id") or record.get("name") or record.get("alpha_id") or "")
            return DuplicateCheck(True, key, duplicate_of=duplicate_of, reason="same_canonical_factor_key")
    return DuplicateCheck(False, key)


def annotate_factor_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    payload = dict(candidate)
    payload.update(canonical_factor_metadata(payload))
    return payload


def dedupe_factor_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for candidate in candidates:
        payload = annotate_factor_identity(candidate)
        key = str(payload["canonical_factor_key"])
        if key in seen:
            continue
        seen.add(key)
        out.append(payload)
    return out


__all__ = ["DuplicateCheck", "annotate_factor_identity", "dedupe_factor_candidates", "find_duplicate_candidate"]
