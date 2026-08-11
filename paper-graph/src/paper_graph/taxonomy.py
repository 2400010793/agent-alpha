"""Versioned quantitative-research taxonomy loading and validation.

The original 12/54 taxonomy remains the immutable compatibility base.  New
topics are supplied as an additive overlay so existing topic identifiers and
historical graph snapshots never change meaning in place.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class TaxonomySummary:
    taxonomy_version: str
    status: str
    first_level_count: int
    second_level_count: int


def validate_taxonomy(taxonomy: Iterable[Mapping[str, Any]]) -> TaxonomySummary:
    """Validate stable identifiers and return derived counts.

    Labels and keywords may evolve additively, but parent and child IDs must be
    globally unique.  The function deliberately derives counts instead of
    enforcing the historical 12/54 shape.
    """

    parents = list(taxonomy)
    parent_ids: set[str] = set()
    child_ids: set[str] = set()
    for parent in parents:
        parent_id = str(parent.get("id") or "").strip()
        label = str(parent.get("label") or "").strip()
        children = parent.get("children")
        if not parent_id or not label:
            raise ValueError("every taxonomy parent requires id and label")
        if parent_id in parent_ids:
            raise ValueError(f"duplicate taxonomy parent id: {parent_id}")
        if not isinstance(children, Mapping) or not children:
            raise ValueError(f"taxonomy parent requires children: {parent_id}")
        parent_ids.add(parent_id)
        for child_id, values in children.items():
            child_id = str(child_id).strip()
            if not child_id:
                raise ValueError(f"empty child id under {parent_id}")
            if child_id in child_ids:
                raise ValueError(f"duplicate taxonomy child id: {child_id}")
            if not isinstance(values, (list, tuple)) or not values or not str(values[0]).strip():
                raise ValueError(f"taxonomy child requires a label: {child_id}")
            child_ids.add(child_id)
    return TaxonomySummary("unversioned", "unknown", len(parent_ids), len(child_ids))


def load_extension(path: Path) -> dict[str, Any]:
    """Load and validate an additive taxonomy overlay."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "quant_research_taxonomy_extension_v1":
        raise ValueError("unsupported taxonomy extension schema_version")
    if payload.get("mode") != "additive_only":
        raise ValueError("taxonomy extensions must use additive_only mode")
    if not str(payload.get("taxonomy_version") or "").strip():
        raise ValueError("taxonomy extension requires taxonomy_version")
    additions = payload.get("add_first_levels")
    if not isinstance(additions, list):
        raise ValueError("taxonomy extension requires add_first_levels")
    validate_taxonomy(additions)
    return payload


def merge_taxonomy(
    base: Iterable[Mapping[str, Any]], extension: Mapping[str, Any] | None = None
) -> tuple[tuple[dict[str, Any], ...], TaxonomySummary]:
    """Merge an additive extension without mutating the compatibility base."""

    merged = [
        {
            "id": str(parent["id"]),
            "label": str(parent["label"]),
            "children": {str(key): tuple(value) for key, value in parent["children"].items()},
        }
        for parent in base
    ]
    base_summary = validate_taxonomy(merged)
    version = "digest_quant_topics_v1"
    status = "stable"
    if extension:
        extension_version = str(extension.get("taxonomy_version") or "").strip()
        expected_parent_count = extension.get("base_first_level_count")
        expected_child_count = extension.get("base_second_level_count")
        if expected_parent_count is not None and int(expected_parent_count) != base_summary.first_level_count:
            raise ValueError("taxonomy extension base_first_level_count does not match base")
        if expected_child_count is not None and int(expected_child_count) != base_summary.second_level_count:
            raise ValueError("taxonomy extension base_second_level_count does not match base")
        additions = extension.get("add_first_levels") or []
        merged.extend(
            {
                "id": str(parent["id"]),
                "label": str(parent["label"]),
                "children": {str(key): tuple(value) for key, value in parent["children"].items()},
            }
            for parent in additions
        )
        version = extension_version
        status = str(extension.get("status") or "candidate")
    summary = validate_taxonomy(merged)
    return tuple(merged), TaxonomySummary(
        taxonomy_version=version,
        status=status,
        first_level_count=summary.first_level_count,
        second_level_count=summary.second_level_count,
    )


__all__ = [
    "TaxonomySummary",
    "load_extension",
    "merge_taxonomy",
    "validate_taxonomy",
]
