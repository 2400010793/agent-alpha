"""Immutable feedback events and safe graph-priority update proposals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .research_contracts import canonical_hash


FEEDBACK_STATUSES = frozenset({"COMPLETED", "FAILED", "INCONCLUSIVE", "CANCELLED"})


@dataclass(frozen=True)
class OpportunityResearchFeedbackV1:
    feedback_id: str
    research_opportunity_id: str
    research_run_id: str
    package_id: str
    target_track: str
    data_contract_hash: str
    status: str
    hypothesis_outcomes: tuple[Mapping[str, Any], ...]
    evidence_gaps: tuple[Mapping[str, Any], ...]
    relation_challenges: tuple[Mapping[str, Any], ...]
    failure_reasons: tuple[str, ...]
    recommendations: tuple[str, ...]
    source_artifact_ids: tuple[str, ...]
    created_at: str
    schema_version: str = "opportunity_research_feedback_v1"

    def __post_init__(self) -> None:
        for name in (
            "feedback_id", "research_opportunity_id", "research_run_id", "package_id",
            "target_track", "data_contract_hash", "status", "created_at",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must be non-empty")
        if self.schema_version != "opportunity_research_feedback_v1":
            raise ValueError("unsupported opportunity feedback schema_version")
        if self.status not in FEEDBACK_STATUSES:
            raise ValueError(f"unsupported feedback status: {self.status}")
        if not self.source_artifact_ids:
            raise ValueError("feedback requires source artifacts")
        expected = "oppfeedback:" + canonical_hash(self.identity_payload())[:24]
        if self.feedback_id != expected:
            raise ValueError("feedback_id does not match immutable feedback inputs")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "research_opportunity_id": self.research_opportunity_id,
            "research_run_id": self.research_run_id,
            "package_id": self.package_id,
            "target_track": self.target_track,
            "data_contract_hash": self.data_contract_hash,
            "status": self.status,
            "hypothesis_outcomes": list(self.hypothesis_outcomes),
            "evidence_gaps": list(self.evidence_gaps),
            "relation_challenges": list(self.relation_challenges),
            "failure_reasons": list(self.failure_reasons),
            "source_artifact_ids": list(self.source_artifact_ids),
        }

    @classmethod
    def create(cls, **values: Any) -> "OpportunityResearchFeedbackV1":
        payload = dict(values)
        for name in (
            "hypothesis_outcomes", "evidence_gaps", "relation_challenges",
            "failure_reasons", "recommendations", "source_artifact_ids",
        ):
            payload[name] = tuple(payload.get(name) or ())
        identity = {
            "research_opportunity_id": payload["research_opportunity_id"],
            "research_run_id": payload["research_run_id"],
            "package_id": payload["package_id"],
            "target_track": payload["target_track"],
            "data_contract_hash": payload["data_contract_hash"],
            "status": payload["status"],
            "hypothesis_outcomes": list(payload["hypothesis_outcomes"]),
            "evidence_gaps": list(payload["evidence_gaps"]),
            "relation_challenges": list(payload["relation_challenges"]),
            "failure_reasons": list(payload["failure_reasons"]),
            "source_artifact_ids": list(payload["source_artifact_ids"]),
        }
        payload["feedback_id"] = "oppfeedback:" + canonical_hash(identity)[:24]
        return cls(**payload)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OpportunityResearchFeedbackV1":
        payload = dict(value)
        for name in (
            "hypothesis_outcomes", "evidence_gaps", "relation_challenges",
            "failure_reasons", "recommendations", "source_artifact_ids",
        ):
            payload[name] = tuple(payload.get(name) or ())
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for name in (
            "hypothesis_outcomes", "evidence_gaps", "relation_challenges",
            "failure_reasons", "recommendations", "source_artifact_ids",
        ):
            value[name] = list(value[name])
        return value


@dataclass(frozen=True)
class GraphFeedbackUpdateV1:
    feedback_update_id: str
    source_feedback_id: str
    research_opportunity_id: str
    action_codes: tuple[str, ...]
    evidence_gap_records: tuple[Mapping[str, Any], ...]
    relation_review_records: tuple[Mapping[str, Any], ...]
    research_archive_records: tuple[Mapping[str, Any], ...]
    priority_adjustment: float
    prohibited_inferences: tuple[str, ...]
    schema_version: str = "graph_feedback_update_v1"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for name in (
            "action_codes", "evidence_gap_records", "relation_review_records",
            "research_archive_records", "prohibited_inferences",
        ):
            value[name] = list(value[name])
        return value


def derive_graph_feedback_update(
    feedback: OpportunityResearchFeedbackV1,
) -> GraphFeedbackUpdateV1:
    """Translate experiment feedback into bounded upstream actions."""

    actions: list[str] = []
    priority_adjustment = 0.0
    outcomes = list(feedback.hypothesis_outcomes)
    accepted = [value for value in outcomes if value.get("decision") == "accepted"]
    rejected = [value for value in outcomes if value.get("decision") in {"rejected", "refuted"}]
    if feedback.evidence_gaps:
        actions.append("REQUEST_EVIDENCE")
    if feedback.relation_challenges:
        actions.append("REVIEW_CLAIM_RELATIONS")
    normalized_failures = " ".join(feedback.failure_reasons).casefold()
    if any(term in normalized_failures for term in ("needs_data", "missing data", "unavailable field")):
        actions.append("MARK_ROUTE_NEEDS_DATA")
    if accepted:
        actions.append("QUEUE_ROBUSTNESS_OR_REPLICATION")
        priority_adjustment += 0.05
    if rejected:
        actions.append("ARCHIVE_SCOPE_BOUND_NEGATIVE_RESULT")
        priority_adjustment -= min(0.10, 0.025 * len(rejected))
    if feedback.status == "INCONCLUSIVE":
        actions.append("PRESERVE_INCONCLUSIVE_RESULT")
    if feedback.status in {"FAILED", "CANCELLED"}:
        actions.append("REVIEW_ENGINEERING_OR_BUDGET_FAILURE")
    if not actions:
        actions.append("ARCHIVE_NO_PRIORITY_CHANGE")
    priority_adjustment = round(max(-0.2, min(0.2, priority_adjustment)), 6)
    archive_records = tuple({
        "hypothesis_id": value.get("hypothesis_id"),
        "decision": value.get("decision"),
        "stage": value.get("stage"),
        "metric_artifact_ids": list(value.get("metric_artifact_ids") or []),
        "target_track": feedback.target_track,
        "data_contract_hash": feedback.data_contract_hash,
    } for value in outcomes)
    identity = {
        "source_feedback_id": feedback.feedback_id,
        "actions": actions,
        "evidence_gaps": list(feedback.evidence_gaps),
        "relation_challenges": list(feedback.relation_challenges),
        "archive_records": list(archive_records),
        "priority_adjustment": priority_adjustment,
    }
    return GraphFeedbackUpdateV1(
        feedback_update_id="graphfeedback:" + canonical_hash(identity)[:24],
        source_feedback_id=feedback.feedback_id,
        research_opportunity_id=feedback.research_opportunity_id,
        action_codes=tuple(dict.fromkeys(actions)),
        evidence_gap_records=feedback.evidence_gaps,
        relation_review_records=feedback.relation_challenges,
        research_archive_records=archive_records,
        priority_adjustment=priority_adjustment,
        prohibited_inferences=(
            "DO_NOT_MARK_PAPER_TRUE_OR_FALSE_FROM_LOCAL_FACTOR_RESULT",
            "DO_NOT_OVERWRITE_VERIFIED_CLAIM_RELATIONS",
            "DO_NOT_TRANSFER_RESULT_ACROSS_DATA_CONTRACTS",
        ),
    )


__all__ = [
    "FEEDBACK_STATUSES",
    "GraphFeedbackUpdateV1",
    "OpportunityResearchFeedbackV1",
    "derive_graph_feedback_update",
]
