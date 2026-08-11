"""Transparent graph-level research portfolio scoring.

This module prioritizes which graph deserves research budget.  It does not
judge whether a paper claim is true or whether a factor is effective.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from .research_contracts import canonical_hash


GRAPH_VALUE_POLICY_VERSION = "graph_value_policy_v1"

DEFAULT_WEIGHTS: Mapping[str, float] = {
    "evidence_readiness": 0.18,
    "data_feasibility": 0.22,
    "direct_observability": 0.10,
    "graph_coherence": 0.10,
    "novelty": 0.16,
    "relation_information": 0.08,
    "downstream_utility": 0.16,
}


def _unit(value: float, name: str) -> float:
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


@dataclass(frozen=True)
class GraphValueFeaturesV1:
    graph_id: str
    topic_ids: tuple[str, ...]
    target_track: str
    evidence_readiness: float
    data_feasibility: float
    direct_observability: float
    graph_coherence: float
    novelty: float
    claim_relation_coverage: float
    contradiction_density: float
    downstream_utility: float
    redundancy: float
    estimated_cost: float
    data_contract_id: str | None = None
    evidence_gap_count: int = 0
    schema_version: str = "graph_value_features_v1"

    def __post_init__(self) -> None:
        if self.schema_version != "graph_value_features_v1":
            raise ValueError("unsupported graph value features schema_version")
        if not str(self.graph_id).strip():
            raise ValueError("graph_id must be non-empty")
        if not self.topic_ids or any(not str(value).strip() for value in self.topic_ids):
            raise ValueError("topic_ids must contain stable IDs")
        if not str(self.target_track).strip():
            raise ValueError("target_track must be non-empty")
        if self.evidence_gap_count < 0:
            raise ValueError("evidence_gap_count cannot be negative")
        for name in (
            "evidence_readiness",
            "data_feasibility",
            "direct_observability",
            "graph_coherence",
            "novelty",
            "claim_relation_coverage",
            "contradiction_density",
            "downstream_utility",
            "redundancy",
            "estimated_cost",
        ):
            _unit(getattr(self, name), name)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GraphValueFeaturesV1":
        payload = dict(value)
        payload["topic_ids"] = tuple(payload.get("topic_ids") or ())
        return cls(**payload)


@dataclass(frozen=True)
class GraphValueAssessmentV1:
    assessment_id: str
    graph_id: str
    target_track: str
    data_contract_id: str | None
    score: float
    priority_tier: str
    recommended_action: str
    components: Mapping[str, float]
    penalties: Mapping[str, float]
    reasons: tuple[str, ...]
    policy_version: str = GRAPH_VALUE_POLICY_VERSION
    schema_version: str = "graph_value_assessment_v1"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reasons"] = list(self.reasons)
        return value


@dataclass(frozen=True)
class PortfolioSelectionV1:
    assessment: GraphValueAssessmentV1
    selected: bool
    selection_reason: str
    cumulative_cost: float


def assess_graph_value(
    features: GraphValueFeaturesV1,
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
) -> GraphValueAssessmentV1:
    """Score one graph and choose the appropriate next research action."""

    if set(weights) != set(DEFAULT_WEIGHTS):
        raise ValueError("graph value weights must define the complete policy component set")
    if abs(sum(float(value) for value in weights.values()) - 1.0) > 1e-9:
        raise ValueError("graph value benefit weights must sum to 1")

    relation_information = min(
        1.0, features.claim_relation_coverage + 0.5 * features.contradiction_density
    )
    components = {
        "evidence_readiness": features.evidence_readiness,
        "data_feasibility": features.data_feasibility,
        "direct_observability": features.direct_observability,
        "graph_coherence": features.graph_coherence,
        "novelty": features.novelty,
        "relation_information": relation_information,
        "downstream_utility": features.downstream_utility,
    }
    penalties = {
        "redundancy": 0.12 * features.redundancy,
        "estimated_cost": 0.08 * features.estimated_cost,
    }
    benefit = sum(float(weights[name]) * value for name, value in components.items())
    score = max(0.0, min(1.0, benefit - sum(penalties.values())))

    reasons = [
        f"evidence_readiness:{features.evidence_readiness:.3f}",
        f"data_feasibility:{features.data_feasibility:.3f}",
        f"novelty:{features.novelty:.3f}",
        f"contradiction_density:{features.contradiction_density:.3f}",
        f"redundancy:{features.redundancy:.3f}",
        f"estimated_cost:{features.estimated_cost:.3f}",
    ]

    if features.evidence_readiness < 0.35:
        action = "BUILD_EVIDENCE"
        tier = "defer"
        reasons.append("hard_gate:insufficient_evidence")
    elif features.data_feasibility <= 0.0:
        action = "NEEDS_DATA"
        tier = "defer"
        reasons.append("hard_gate:no_eligible_data_route")
    elif features.contradiction_density >= 0.15 and features.claim_relation_coverage >= 0.35:
        action = "RESOLVE_CONTRADICTION"
        tier = "high" if score >= 0.55 else "medium"
        reasons.append("route:contradiction_resolution")
    elif features.direct_observability >= 0.65 and features.data_feasibility >= 0.65:
        action = "RUN_FACTOR_RESEARCH"
        tier = "high" if score >= 0.70 else "medium" if score >= 0.48 else "low"
        reasons.append("route:observable_factor_research")
    elif features.downstream_utility >= 0.65:
        action = "RUN_FEATURE_OR_METHOD_RESEARCH"
        tier = "high" if score >= 0.70 else "medium" if score >= 0.48 else "low"
        reasons.append("route:feature_or_method_research")
    else:
        action = "REVIEW_RESEARCH_OPPORTUNITY"
        tier = "medium" if score >= 0.48 else "low"
        reasons.append("route:manual_opportunity_review")

    identity = {
        "features": asdict(features),
        "components": components,
        "penalties": penalties,
        "policy_version": GRAPH_VALUE_POLICY_VERSION,
    }
    return GraphValueAssessmentV1(
        assessment_id="graphvalue:" + canonical_hash(identity)[:24],
        graph_id=features.graph_id,
        target_track=features.target_track,
        data_contract_id=features.data_contract_id,
        score=round(score, 6),
        priority_tier=tier,
        recommended_action=action,
        components={name: round(value, 6) for name, value in components.items()},
        penalties={name: round(value, 6) for name, value in penalties.items()},
        reasons=tuple(reasons),
    )


class ResearchPortfolioController:
    """Select graph assessments under explicit budget and diversity limits."""

    def select(
        self,
        candidates: Iterable[tuple[GraphValueFeaturesV1, GraphValueAssessmentV1]],
        *,
        max_graphs: int,
        cost_budget: float,
        max_per_primary_topic: int = 2,
    ) -> list[PortfolioSelectionV1]:
        if max_graphs < 1 or max_per_primary_topic < 1:
            raise ValueError("portfolio count limits must be positive")
        if cost_budget < 0:
            raise ValueError("cost_budget cannot be negative")
        ordered = sorted(candidates, key=lambda item: (-item[1].score, item[1].graph_id))
        selected_count = 0
        cumulative_cost = 0.0
        topic_counts: dict[str, int] = {}
        result: list[PortfolioSelectionV1] = []
        for features, assessment in ordered:
            primary_topic = features.topic_ids[0]
            eligible = assessment.priority_tier != "defer"
            reason = "selected"
            if not eligible:
                reason = f"not_executable:{assessment.recommended_action}"
            elif selected_count >= max_graphs:
                reason = "portfolio_graph_limit"
            elif topic_counts.get(primary_topic, 0) >= max_per_primary_topic:
                reason = "primary_topic_diversity_limit"
            elif cumulative_cost + features.estimated_cost > cost_budget + 1e-12:
                reason = "portfolio_cost_limit"
            selected = reason == "selected"
            if selected:
                selected_count += 1
                cumulative_cost += features.estimated_cost
                topic_counts[primary_topic] = topic_counts.get(primary_topic, 0) + 1
            result.append(PortfolioSelectionV1(
                assessment=assessment,
                selected=selected,
                selection_reason=reason,
                cumulative_cost=round(cumulative_cost, 6),
            ))
        return result


__all__ = [
    "DEFAULT_WEIGHTS",
    "GRAPH_VALUE_POLICY_VERSION",
    "GraphValueAssessmentV1",
    "GraphValueFeaturesV1",
    "PortfolioSelectionV1",
    "ResearchPortfolioController",
    "assess_graph_value",
]
