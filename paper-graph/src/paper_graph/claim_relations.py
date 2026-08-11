"""Evidence-backed claim relations that can be projected into paper graphs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from .models import EPISTEMIC_EDGE_TYPES, PaperEdge
from .research_contracts import canonical_hash


CLAIM_RELATION_TYPES = EPISTEMIC_EDGE_TYPES
SCOPE_ALIGNMENTS = frozenset({"exact", "partial", "incompatible", "unclear"})
REVIEW_STATUSES = frozenset({"proposed", "verified", "rejected", "superseded"})


def _nonempty_tuple(values: Iterable[Any], name: str) -> tuple[str, ...]:
    result = tuple(str(value).strip() for value in values if str(value).strip())
    if not result:
        raise ValueError(f"{name} must contain at least one stable ID")
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must not contain duplicate IDs")
    return result


@dataclass(frozen=True)
class ClaimRelationV1:
    """One directional, evidence-backed relation between two paper claims.

    Direction is always ``source claim RELATION target claim``.  For example,
    a later replication paper may ``SUPPORTS`` or ``FAILS_TO_REPLICATE`` the
    target paper's earlier claim.
    """

    relation_id: str
    source_paper_id: str
    target_paper_id: str
    source_claim_id: str
    target_claim_id: str
    relation_type: str
    source_evidence_ids: tuple[str, ...]
    target_evidence_ids: tuple[str, ...]
    scope_alignment: str
    confidence: float
    review_status: str
    extraction_method: str
    rationale: str
    document_versions: Mapping[str, str]
    reviewer: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "claim_relation_v1"

    def __post_init__(self) -> None:
        for name in (
            "relation_id",
            "source_paper_id",
            "target_paper_id",
            "source_claim_id",
            "target_claim_id",
            "relation_type",
            "scope_alignment",
            "review_status",
            "extraction_method",
            "rationale",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must be non-empty")
        if self.schema_version != "claim_relation_v1":
            raise ValueError("unsupported claim relation schema_version")
        if self.source_paper_id == self.target_paper_id and self.source_claim_id == self.target_claim_id:
            raise ValueError("a claim relation cannot be a self-loop")
        if self.relation_type not in CLAIM_RELATION_TYPES:
            raise ValueError(f"unsupported claim relation_type: {self.relation_type}")
        if self.scope_alignment not in SCOPE_ALIGNMENTS:
            raise ValueError(f"unsupported scope_alignment: {self.scope_alignment}")
        if self.review_status not in REVIEW_STATUSES:
            raise ValueError(f"unsupported review_status: {self.review_status}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "source_evidence_ids", _nonempty_tuple(self.source_evidence_ids, "source_evidence_ids"))
        object.__setattr__(self, "target_evidence_ids", _nonempty_tuple(self.target_evidence_ids, "target_evidence_ids"))
        if not self.document_versions.get(self.source_paper_id):
            raise ValueError("document_versions must pin the source paper version")
        if not self.document_versions.get(self.target_paper_id):
            raise ValueError("document_versions must pin the target paper version")
        if self.review_status == "verified" and not str(self.reviewer or "").strip():
            raise ValueError("verified claim relations require a reviewer")
        if self.relation_type in {"CONTRADICTS", "FAILS_TO_REPLICATE"} and self.scope_alignment in {"incompatible", "unclear"}:
            raise ValueError(
                "contradiction/replication-failure requires exact or partial scope alignment"
            )
        expected = "claimrel:" + canonical_hash(self.identity_payload())[:24]
        if self.relation_id != expected:
            raise ValueError("relation_id does not match immutable claim relation inputs")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "source_paper_id": self.source_paper_id,
            "target_paper_id": self.target_paper_id,
            "source_claim_id": self.source_claim_id,
            "target_claim_id": self.target_claim_id,
            "relation_type": self.relation_type,
            "source_evidence_ids": list(self.source_evidence_ids),
            "target_evidence_ids": list(self.target_evidence_ids),
            "scope_alignment": self.scope_alignment,
            "document_versions": dict(self.document_versions),
        }

    @classmethod
    def create(cls, **values: Any) -> "ClaimRelationV1":
        payload = dict(values)
        payload["source_evidence_ids"] = tuple(payload.get("source_evidence_ids") or ())
        payload["target_evidence_ids"] = tuple(payload.get("target_evidence_ids") or ())
        identity = {
            "source_paper_id": payload["source_paper_id"],
            "target_paper_id": payload["target_paper_id"],
            "source_claim_id": payload["source_claim_id"],
            "target_claim_id": payload["target_claim_id"],
            "relation_type": payload["relation_type"],
            "source_evidence_ids": list(payload["source_evidence_ids"]),
            "target_evidence_ids": list(payload["target_evidence_ids"]),
            "scope_alignment": payload["scope_alignment"],
            "document_versions": dict(payload["document_versions"]),
        }
        payload["relation_id"] = "claimrel:" + canonical_hash(identity)[:24]
        return cls(**payload)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ClaimRelationV1":
        payload = dict(value)
        payload["source_evidence_ids"] = tuple(payload.get("source_evidence_ids") or ())
        payload["target_evidence_ids"] = tuple(payload.get("target_evidence_ids") or ())
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_evidence_ids"] = list(self.source_evidence_ids)
        value["target_evidence_ids"] = list(self.target_evidence_ids)
        return value

    def to_paper_edge(self) -> PaperEdge:
        if self.review_status != "verified":
            raise ValueError("only verified claim relations may become graph edges")
        return PaperEdge(
            source=self.source_paper_id,
            target=self.target_paper_id,
            relation=self.relation_type,  # type: ignore[arg-type]
            weight=float(self.confidence),
            metadata={
                "relation_id": self.relation_id,
                "source_claim_id": self.source_claim_id,
                "target_claim_id": self.target_claim_id,
                "source_evidence_ids": list(self.source_evidence_ids),
                "target_evidence_ids": list(self.target_evidence_ids),
                "scope_alignment": self.scope_alignment,
                "review_status": self.review_status,
                "extraction_method": self.extraction_method,
                "reviewer": self.reviewer,
                "document_versions": dict(self.document_versions),
                "rationale": self.rationale,
                **dict(self.metadata),
            },
        )


def project_verified_relations(
    relations: Iterable[ClaimRelationV1], node_ids: Iterable[str] | None = None
) -> list[PaperEdge]:
    """Project verified relations whose endpoints exist in a bounded graph."""

    allowed = set(node_ids) if node_ids is not None else None
    result: list[PaperEdge] = []
    seen: set[str] = set()
    for relation in relations:
        if relation.review_status != "verified" or relation.relation_id in seen:
            continue
        if allowed is not None and (
            relation.source_paper_id not in allowed or relation.target_paper_id not in allowed
        ):
            continue
        result.append(relation.to_paper_edge())
        seen.add(relation.relation_id)
    return result


__all__ = [
    "CLAIM_RELATION_TYPES",
    "ClaimRelationV1",
    "REVIEW_STATUSES",
    "SCOPE_ALIGNMENTS",
    "project_verified_relations",
]
