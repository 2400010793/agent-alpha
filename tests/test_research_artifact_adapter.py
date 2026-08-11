from agent_alpha.adapters.research_artifact import reading_note_from_envelope, validate_research_artifact_envelope


def test_adapter_uses_embedded_note_without_crawling() -> None:
    envelope = {"schema_version": "research_artifact_envelope_v1", "artifact_id": "artifact:1", "canonical_paper_id": "arxiv:1", "openalex_id": "W1", "title": "Paper", "reading_note_id": "note:1", "reading_note": {"schema_version": "reading_note_v1", "recommendation_score": 8}, "evidence_spans": [{"evidence_id": "ev:1", "chunk_id": "chunk:1"}]}
    assert validate_research_artifact_envelope(envelope)["artifact_id"] == "artifact:1"
    assert reading_note_from_envelope(envelope)["recommendation_score"] == 8
