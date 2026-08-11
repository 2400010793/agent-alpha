"""Import ResearchArtifactEnvelopeV1 without crawling or parsing papers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


REQUIRED = {"artifact_id", "canonical_paper_id", "openalex_id", "title", "reading_note_id", "reading_note", "evidence_spans"}


def validate_research_artifact_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    if payload.get("schema_version") != "research_artifact_envelope_v1":
        raise ValueError("unsupported research artifact schema")
    missing = sorted(key for key in REQUIRED if not payload.get(key))
    if missing:
        raise ValueError(f"research artifact missing keys: {missing}")
    if payload["reading_note"].get("schema_version") != "reading_note_v1":
        raise ValueError("embedded reading note must use reading_note_v1")
    evidence_ids = [str(item.get("evidence_id") or "") for item in payload["evidence_spans"]]
    if any(not value for value in evidence_ids) or len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("research artifact evidence IDs must be stable and unique")
    return payload


def load_research_artifact_envelope(path: str | Path) -> dict[str, Any]:
    return validate_research_artifact_envelope(json.loads(Path(path).read_text(encoding="utf-8")))


def reading_note_from_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    return dict(validate_research_artifact_envelope(value)["reading_note"])


__all__ = ["load_research_artifact_envelope", "reading_note_from_envelope", "validate_research_artifact_envelope"]
