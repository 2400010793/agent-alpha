"""Versioned OpenAlex filter profiles.

The explicit profile switch keeps long-running v4 jobs reproducible while
allowing v5 to be applied to either raw Works or the compact v4 candidate set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from paper_graph.finance_audit import FINANCE_AUDIT_VERSION as V4_AUDIT_VERSION
from paper_graph.finance_audit import audit_finance_context
from paper_graph.finance_filter_v5 import (
    FINANCE_AUDIT_VERSION as V5_AUDIT_VERSION,
    RESEARCH_VALUE_VERSION as V5_VALUE_VERSION,
    SELECTION_VERSION as V5_SELECTION_VERSION,
    assess_research_value_v2,
    audit_finance_context_v5,
    classify_quant_work_v2,
)
from paper_graph.openalex_snapshot import classify_quant_work
from paper_graph.research_value import RESEARCH_VALUE_VERSION as V4_VALUE_VERSION
from paper_graph.research_value import assess_research_value


@dataclass(frozen=True)
class FilterProfile:
    name: str
    selection_version: str
    finance_audit_version: str
    research_value_version: str
    classify: Callable[[Mapping[str, Any]], dict[str, Any]]
    audit: Callable[[Mapping[str, Any], Mapping[str, Any]], Any]
    assess_value: Callable[[Mapping[str, Any], Any], Any]


FILTER_PROFILES = {
    "v4": FilterProfile(
        "v4", "openalex_85_keyword_v1", V4_AUDIT_VERSION, V4_VALUE_VERSION,
        classify_quant_work, audit_finance_context, assess_research_value,
    ),
    "v5": FilterProfile(
        "v5", V5_SELECTION_VERSION, V5_AUDIT_VERSION, V5_VALUE_VERSION,
        classify_quant_work_v2, audit_finance_context_v5, assess_research_value_v2,
    ),
}


def get_filter_profile(name: str) -> FilterProfile:
    try:
        return FILTER_PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown filter profile: {name!r}") from exc


__all__ = ["FILTER_PROFILES", "FilterProfile", "get_filter_profile"]
