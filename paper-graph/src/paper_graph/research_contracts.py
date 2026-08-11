"""Versioned artifacts exchanged by Paper Graph, Paper Digest, and Agent Alpha."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _required(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


@dataclass(frozen=True)
class ResearchArtifactEnvelopeV1:
    artifact_id: str
    producer_project: str
    config_hash: str
    canonical_paper_id: str
    openalex_id: str
    title: str
    finance_status: str
    graph_seed_provenance: Mapping[str, Any]
    digest_content_version: str
    reading_note_id: str
    reading_note: Mapping[str, Any]
    evidence_spans: tuple[Mapping[str, Any], ...]
    extraction_config: Mapping[str, Any]
    run_manifest: Mapping[str, Any]
    arxiv_id: str | None = None
    arxiv_version: int | None = None
    doi: str | None = None
    authors: tuple[Mapping[str, Any], ...] = ()
    publication_date: str | None = None
    schema_version: str = "research_artifact_envelope_v1"

    def __post_init__(self) -> None:
        for name in ("artifact_id", "producer_project", "config_hash", "canonical_paper_id", "openalex_id", "title", "finance_status", "digest_content_version", "reading_note_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.schema_version != "research_artifact_envelope_v1":
            raise ValueError("unsupported artifact schema_version")
        if self.reading_note.get("schema_version") != "reading_note_v1":
            raise ValueError("reading_note must use reading_note_v1")
        evidence_ids = [str(item.get("evidence_id") or "") for item in self.evidence_spans]
        if not evidence_ids or any(not value for value in evidence_ids) or len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence_spans require unique stable evidence_id values")
        expected = "artifact:" + canonical_hash(self.identity_payload())[:24]
        if self.artifact_id != expected:
            raise ValueError("artifact_id does not match immutable envelope inputs")

    def identity_payload(self) -> dict[str, Any]:
        return {"canonical_paper_id": self.canonical_paper_id, "config_hash": self.config_hash, "digest_content_version": self.digest_content_version, "reading_note_id": self.reading_note_id, "evidence_ids": [item["evidence_id"] for item in self.evidence_spans]}

    @classmethod
    def create(cls, **values: Any) -> "ResearchArtifactEnvelopeV1":
        values = dict(values)
        values.setdefault("schema_version", "research_artifact_envelope_v1")
        values.setdefault("authors", ())
        values["authors"] = tuple(values["authors"])
        values["evidence_spans"] = tuple(values["evidence_spans"])
        identity = {"canonical_paper_id": values["canonical_paper_id"], "config_hash": values["config_hash"], "digest_content_version": values["digest_content_version"], "reading_note_id": values["reading_note_id"], "evidence_ids": [item["evidence_id"] for item in values["evidence_spans"]]}
        values["artifact_id"] = "artifact:" + canonical_hash(identity)[:24]
        return cls(**values)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ResearchArtifactEnvelopeV1":
        payload = dict(value)
        payload["authors"] = tuple(payload.get("authors") or ())
        payload["evidence_spans"] = tuple(payload.get("evidence_spans") or ())
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "authors": list(self.authors), "evidence_spans": list(self.evidence_spans)}


@dataclass(frozen=True)
class ResearchFeedbackV1:
    feedback_id: str
    source_artifact_id: str
    canonical_paper_id: str
    accepted_factors: tuple[Mapping[str, Any], ...] = ()
    rejected_factors: tuple[Mapping[str, Any], ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    factor_lineage: tuple[Mapping[str, Any], ...] = ()
    mechanism_performance: Mapping[str, Any] = field(default_factory=dict)
    evidence_gaps: tuple[str, ...] = ()
    failure_reasons: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    schema_version: str = "research_feedback_v1"

    def __post_init__(self) -> None:
        for name in ("feedback_id", "source_artifact_id", "canonical_paper_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.schema_version != "research_feedback_v1":
            raise ValueError("unsupported feedback schema_version")
        expected = "feedback:" + canonical_hash({"source_artifact_id": self.source_artifact_id, "canonical_paper_id": self.canonical_paper_id, "accepted_factors": self.accepted_factors, "rejected_factors": self.rejected_factors, "metrics": self.metrics})[:24]
        if self.feedback_id != expected:
            raise ValueError("feedback_id does not match immutable feedback inputs")

    @classmethod
    def create(cls, **values: Any) -> "ResearchFeedbackV1":
        values = dict(values)
        for name in ("accepted_factors", "rejected_factors", "factor_lineage", "evidence_gaps", "failure_reasons", "recommendations", "evidence_ids"):
            values[name] = tuple(values.get(name) or ())
        identity = {"source_artifact_id": values["source_artifact_id"], "canonical_paper_id": values["canonical_paper_id"], "accepted_factors": values["accepted_factors"], "rejected_factors": values["rejected_factors"], "metrics": values.get("metrics") or {}}
        values["feedback_id"] = "feedback:" + canonical_hash(identity)[:24]
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "accepted_factors": list(self.accepted_factors), "rejected_factors": list(self.rejected_factors), "factor_lineage": list(self.factor_lineage), "evidence_gaps": list(self.evidence_gaps), "failure_reasons": list(self.failure_reasons), "recommendations": list(self.recommendations), "evidence_ids": list(self.evidence_ids)}


__all__ = ["ResearchArtifactEnvelopeV1", "ResearchFeedbackV1", "canonical_hash"]
