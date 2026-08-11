from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from agent_alpha.factors.prefix_expression import fields_from_prefix, windows_from_prefix
from agent_alpha.search.mutation_guard import canonical_prefix


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def canonical_factor_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    prefix = candidate.get("prefix_expression")
    canonical = canonical_prefix(prefix) if prefix is not None else None
    fields = _as_str_list(candidate.get("fields"))
    windows = [int(item) for item in candidate.get("windows", []) if isinstance(item, (int, float, str)) and str(item).strip().lstrip("-").isdigit()]
    if canonical is not None:
        try:
            fields = fields or fields_from_prefix(canonical)
            windows = windows or windows_from_prefix(canonical)
        except Exception:
            pass
    return {
        "canonical_prefix_expression": canonical,
        "fields": sorted(set(fields)),
        "windows": sorted(set(windows)),
        "direction": str(candidate.get("direction") or candidate.get("expected_direction") or "unknown"),
    }


def canonical_factor_key(candidate: dict[str, Any]) -> str:
    return _stable_hash(canonical_factor_payload(candidate))


def canonical_factor_metadata(candidate: dict[str, Any]) -> dict[str, Any]:
    payload = canonical_factor_payload(candidate)
    definition_key = canonical_factor_key(candidate)
    instance_key = _stable_hash(
        {
            "factor_definition_id": f"fdef_{definition_key}",
            "research_run_id": str(candidate.get("research_run_id") or ""),
            "graph_id": str(candidate.get("graph_id") or ""),
            "graph_version": str(candidate.get("graph_version") or ""),
            "hypothesis_id": str(candidate.get("hypothesis_id") or ""),
            "source_signal_id": str(candidate.get("source_signal_id") or ""),
            "evidence_ids": sorted(_as_str_list(candidate.get("evidence_ids"))),
        }
    )
    return {
        "canonical_factor_key": definition_key,
        "factor_definition_id": f"fdef_{definition_key}",
        "factor_instance_id": f"finst_{instance_key}",
        "canonical_prefix_expression": payload["canonical_prefix_expression"],
        "canonical_fields": payload["fields"],
        "canonical_windows": payload["windows"],
        "canonical_direction": payload["direction"],
    }


def lineage_edge_key(parent_candidate: dict[str, Any], child_candidate: dict[str, Any], mutation_type: str) -> str:
    return _stable_hash(
        {
            "parent": canonical_factor_key(parent_candidate),
            "child": canonical_factor_key(child_candidate),
            "mutation_type": str(mutation_type or ""),
        }
    )


__all__ = ["canonical_factor_key", "canonical_factor_metadata", "canonical_factor_payload", "lineage_edge_key"]
