"""Export Paper Digest evidence as ResearchArtifactEnvelopeV1-compatible JSON."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def export_research_artifact_envelope(
    *, paper: Mapping[str, Any], graph_seed: Mapping[str, Any], reading_note: Mapping[str, Any],
    evidence_spans: list[Mapping[str, Any]], extraction_config: Mapping[str, Any],
    run_manifest: Mapping[str, Any], digest_content_version: str = "paper_digest_content_v1",
) -> dict[str, Any]:
    if reading_note.get("schema_version") != "reading_note_v1":
        raise ValueError("reading_note must use reading_note_v1")
    if not evidence_spans:
        raise ValueError("evidence_spans must be non-empty")
    evidence_ids = [str(item.get("evidence_id") or "") for item in evidence_spans]
    if any(not value for value in evidence_ids) or len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("evidence IDs must be non-empty and unique")
    reading_note_id = str(reading_note.get("reading_note_id") or ("note:" + _hash(reading_note)[:24]))
    config_hash = _hash(extraction_config)
    identity = {"canonical_paper_id": paper["canonical_paper_id"], "config_hash": config_hash, "digest_content_version": digest_content_version, "reading_note_id": reading_note_id, "evidence_ids": evidence_ids}
    return {
        "schema_version": "research_artifact_envelope_v1",
        "artifact_id": "artifact:" + _hash(identity)[:24],
        "producer_project": "my-paper-digest-new2",
        "config_hash": config_hash,
        "canonical_paper_id": paper["canonical_paper_id"],
        "openalex_id": paper["openalex_id"],
        "arxiv_id": paper.get("arxiv_id"), "arxiv_version": paper.get("arxiv_version"),
        "doi": paper.get("doi"), "title": paper["title"], "authors": list(paper.get("authors") or []),
        "publication_date": paper.get("publication_date"), "finance_status": paper["finance_status"],
        "graph_seed_provenance": dict(graph_seed), "digest_content_version": digest_content_version,
        "reading_note_id": reading_note_id, "reading_note": dict(reading_note),
        "evidence_spans": [dict(item) for item in evidence_spans],
        "extraction_config": dict(extraction_config), "run_manifest": dict(run_manifest),
    }


__all__ = ["export_research_artifact_envelope"]
