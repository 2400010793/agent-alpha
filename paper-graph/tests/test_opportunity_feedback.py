from paper_graph.opportunity_feedback import (
    OpportunityResearchFeedbackV1,
    derive_graph_feedback_update,
)


def test_feedback_separates_evidence_relation_and_empirical_actions() -> None:
    feedback = OpportunityResearchFeedbackV1.create(
        research_opportunity_id="opportunity:one",
        research_run_id="run:one",
        package_id="researchpkg:one",
        target_track="intraday_hf",
        data_contract_hash="datahash",
        status="COMPLETED",
        hypothesis_outcomes=[{
            "hypothesis_id": "hypothesis:ofi",
            "decision": "refuted",
            "stage": "validation",
            "metric_artifact_ids": ["metric:one"],
        }],
        evidence_gaps=[{"paper_id": "paper:one", "missing": "sample definition"}],
        relation_challenges=[{"relation_id": "claimrel:one", "reason": "scope mismatch"}],
        failure_reasons=[],
        recommendations=[],
        source_artifact_ids=["review:one"],
        created_at="2026-08-11T00:00:00Z",
    )
    update = derive_graph_feedback_update(feedback)
    assert "REQUEST_EVIDENCE" in update.action_codes
    assert "REVIEW_CLAIM_RELATIONS" in update.action_codes
    assert "ARCHIVE_SCOPE_BOUND_NEGATIVE_RESULT" in update.action_codes
    assert update.priority_adjustment < 0
    assert "DO_NOT_MARK_PAPER_TRUE_OR_FALSE_FROM_LOCAL_FACTOR_RESULT" in update.prohibited_inferences


def test_accepted_local_result_only_requests_robustness() -> None:
    feedback = OpportunityResearchFeedbackV1.create(
        research_opportunity_id="opportunity:one",
        research_run_id="run:one",
        package_id="researchpkg:one",
        target_track="daily_cross_sectional",
        data_contract_hash="dailyhash",
        status="COMPLETED",
        hypothesis_outcomes=[{
            "hypothesis_id": "hypothesis:momentum",
            "decision": "accepted",
            "stage": "validation",
            "metric_artifact_ids": ["metric:one"],
        }],
        evidence_gaps=[],
        relation_challenges=[],
        failure_reasons=[],
        recommendations=[],
        source_artifact_ids=["review:one"],
        created_at="2026-08-11T00:00:00Z",
    )
    update = derive_graph_feedback_update(feedback)
    assert update.action_codes == ("QUEUE_ROBUSTNESS_OR_REPLICATION",)
    assert update.priority_adjustment == 0.05
