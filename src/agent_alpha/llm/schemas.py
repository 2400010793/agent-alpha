from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EvidenceRef:
    source_id: str
    quote: str = ""
    location: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReadingNote:
    paper_id: str
    paper_title: str
    central_claim: str
    mechanism_chain: list[str] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    schema_version: str = "reading_note_v1"
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [item.to_dict() for item in self.evidence]
        return data


@dataclass
class AlphaSignal:
    signal_id: str
    source_paper_id: str
    signal_name: str
    market_intuition: str
    hypothesis: str
    expected_direction: Literal["positive", "negative", "conditional", "unknown"] = "unknown"
    hf_mechanism_tags: list[str] = field(default_factory=list)
    candidate_fields: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    schema_version: str = "alpha_signal_v1"
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FactorCandidate:
    factor_id: str
    source_signal_id: str
    factor_name: str
    factor_expression: str
    fields: list[str]
    hf_mechanism_tags: list[str] = field(default_factory=list)
    cogalpha_roles: list[str] = field(default_factory=list)
    memory_archetype_ids: list[str] = field(default_factory=list)
    expected_direction: Literal["positive", "negative", "conditional", "unknown"] = "unknown"
    economic_rationale: str = ""
    validation_status: str = "pending"
    schema_version: str = "factor_candidate_v1"
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchReviewRecord:
    review_id: str
    factor_id: str
    decision: Literal["accept", "revise", "reject"]
    statistical_summary: str = ""
    risk_summary: str = ""
    economic_logic_summary: str = ""
    implementation_quality_summary: str = ""
    required_revisions: list[str] = field(default_factory=list)
    schema_version: str = "research_review_v1"
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)