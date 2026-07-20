from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SCORE_DIMENSIONS = (
    "relevance",
    "mechanism",
    "statistical",
    "implementation",
    "cost_sensitivity",
    "generality",
)


@dataclass(frozen=True)
class ReadingGateConfig:
    min_recommendation_score: float = 5.5
    require_evidence: bool = True
    require_trading_intuition: bool = True
    min_mechanism_chain_items: int = 1
    gated_pipeline_name: str = "agent-alpha-reading-gated-v1"
    gated_reason_prefix: str = "reading_score_below_threshold"

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ReadingGateConfig":
        return cls(
            min_recommendation_score=float(payload.get("min_recommendation_score", 5.5)),
            require_evidence=bool(payload.get("require_evidence", True)),
            require_trading_intuition=bool(payload.get("require_trading_intuition", True)),
            min_mechanism_chain_items=int(payload.get("min_mechanism_chain_items", 1)),
            gated_pipeline_name=str(payload.get("gated_pipeline_name", "agent-alpha-reading-gated-v1")),
            gated_reason_prefix=str(payload.get("gated_reason_prefix", "reading_score_below_threshold")),
        )


@dataclass
class ReadingGateDecision:
    should_continue: bool
    reading_score: float
    reasons: list[str] = field(default_factory=list)
    pipeline_name: str = "agent-alpha-reading-gated-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_continue": self.should_continue,
            "reading_score": self.reading_score,
            "reasons": self.reasons,
            "pipeline_name": self.pipeline_name,
        }


def reading_note_score(reading_note: dict[str, Any]) -> float:
    """Score a reading note using the same idea as new2 three_ai.

    Prefer the six score_dimensions. Fall back to recommendation_score when
    dimension scores are missing.
    """
    dimensions = reading_note.get("score_dimensions")
    scores: list[float] = []
    if isinstance(dimensions, dict):
        for key in SCORE_DIMENSIONS:
            value = dimensions.get(key)
            if not isinstance(value, dict):
                continue
            try:
                score = float(value.get("score") or 0)
            except (TypeError, ValueError):
                continue
            if score > 0:
                scores.append(score)
    if scores:
        return round(sum(scores) / len(scores), 2)
    try:
        return round(float(reading_note.get("recommendation_score") or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _nonempty_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value] if value else []


def evaluate_reading_gate(reading_note: dict[str, Any], config: ReadingGateConfig | None = None) -> ReadingGateDecision:
    cfg = config or ReadingGateConfig()
    score = reading_note_score(reading_note)
    reasons: list[str] = []
    if score < cfg.min_recommendation_score:
        reasons.append(f"{cfg.gated_reason_prefix}:{score}<{cfg.min_recommendation_score}")
    if cfg.require_evidence and not _nonempty_list(reading_note.get("supporting_evidence") or reading_note.get("evidence")):
        reasons.append("missing_supporting_evidence")
    if cfg.require_trading_intuition and not _nonempty_list(reading_note.get("possible_trading_intuitions")):
        reasons.append("missing_possible_trading_intuitions")
    mechanism_items = _nonempty_list(reading_note.get("mechanism_chain"))
    if len(mechanism_items) < cfg.min_mechanism_chain_items:
        reasons.append(f"mechanism_chain_too_short:{len(mechanism_items)}<{cfg.min_mechanism_chain_items}")
    return ReadingGateDecision(
        should_continue=not reasons,
        reading_score=score,
        reasons=reasons,
        pipeline_name=cfg.gated_pipeline_name,
    )