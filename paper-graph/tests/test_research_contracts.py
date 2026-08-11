from paper_graph.research_contracts import ResearchArtifactEnvelopeV1, ResearchFeedbackV1


def test_artifact_and_feedback_round_trip() -> None:
    artifact = ResearchArtifactEnvelopeV1.create(producer_project="my-paper-digest-new2", config_hash="cfg", canonical_paper_id="arxiv:2105.13727", openalex_id="W1", arxiv_id="2105.13727", title="Slow Momentum", finance_status="accepted", graph_seed_provenance={"seed_rank": 1}, digest_content_version="digest-v1", reading_note_id="note-1", reading_note={"schema_version": "reading_note_v1"}, evidence_spans=[{"evidence_id": "ev-1", "chunk_id": "chunk-1"}], extraction_config={}, run_manifest={})
    assert ResearchArtifactEnvelopeV1.from_mapping(artifact.to_dict()) == artifact
    feedback = ResearchFeedbackV1.create(source_artifact_id=artifact.artifact_id, canonical_paper_id=artifact.canonical_paper_id, accepted_factors=[{"factor_id": "f1"}], metrics={"rankic": 0.01}, evidence_ids=["ev-1"])
    assert feedback.feedback_id.startswith("feedback:")
