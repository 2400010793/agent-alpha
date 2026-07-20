from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class EvaluationRecord:
    evaluation_id: str
    factor_id: str
    factor_name: str
    decision: str
    metrics: dict[str, Any]
    statistical_summary: str
    implementation_summary: str
    economic_summary: str
    risk_summary: str
    failure_modes: list[str] = field(default_factory=list)
    good_patterns: list[str] = field(default_factory=list)
    bad_patterns: list[str] = field(default_factory=list)
    required_revisions: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FeedbackMemoryRecord:
    feedback_id: str
    factor_id: str
    label: str
    reason: str
    reusable_principle: str
    avoid_rule: str
    suggested_next_action: str
    mechanism_tags: list[str]
    prefix_expression: Any
    metrics: dict[str, Any]
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["EvaluationRecord", "FeedbackMemoryRecord", "utc_now_iso"]