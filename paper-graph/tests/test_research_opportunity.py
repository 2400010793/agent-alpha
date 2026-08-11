import pytest

from paper_graph.graph_value import GraphValueFeaturesV1, assess_graph_value
from paper_graph.research_opportunity import (
    StructuredPaperArtifactRefV1,
    build_factor_research_package,
    build_research_opportunity,
)


def _assessment(**overrides):
    values = {
        "graph_id": "graph:ofi",
        "topic_ids": ("order_flow_imbalance",),
        "target_track": "intraday_hf",
        "data_contract_id": "intraday_hf_v1",
        "evidence_readiness": 0.9,
        "data_feasibility": 0.9,
        "direct_observability": 0.9,
        "graph_coherence": 0.8,
        "novelty": 0.7,
        "claim_relation_coverage": 0.4,
        "contradiction_density": 0.0,
        "downstream_utility": 0.9,
        "redundancy": 0.1,
        "estimated_cost": 0.2,
    }
    values.update(overrides)
    return assess_graph_value(GraphValueFeaturesV1(**values))


def _graph():
    return {
        "schema_version": "paper_graph_test_v1",
        "graph_id": "graph:ofi",
        "topic_id": "order_flow_imbalance",
        "seed_ids": ["paper:seed"],
        "nodes": [
            {"id": "paper:seed", "is_seed": True},
            {"id": "paper:neighbor", "is_seed": False},
        ],
        "edges": [],
    }


def _artifact(paper_id="paper:seed"):
    return StructuredPaperArtifactRefV1(
        artifact_id=f"artifact:{paper_id}",
        paper_id=paper_id,
        document_version="v1",
        content_hash=f"sha256:{paper_id}",
        claim_ids=(f"claim:{paper_id}",),
        evidence_ids=(f"evidence:{paper_id}",),
        contribution_types=("MEASUREMENT_FEATURE",),
    )


def test_ready_opportunity_becomes_agent_alpha_package() -> None:
    opportunity = build_research_opportunity(
        _graph(), [_artifact()], [], _assessment(),
        as_of_date="2026-08-11",
        taxonomy_version="quant_research_topics_v2_candidate",
        research_question="Does multi-level OFI improve short-horizon return prediction?",
        required_observables=["L2_BOOK_SNAPSHOT"],
        producer_revision="test-rev",
        config_hash="cfg",
    )
    assert opportunity.status == "READY"
    assert opportunity.missing_evidence_paper_ids == ("paper:neighbor",)
    package = build_factor_research_package(
        opportunity,
        target_track="intraday_hf",
        data_contract_id="intraday_hf_v1",
        data_contract_hash="datahash",
        field_registry_version="fields-v1",
        operator_registry_version="ops-v1",
        memory_snapshot_id="memory-v1",
        research_budget={"max_hypotheses": 2},
        selection_trace={"rank": 1},
    )
    assert package.package_id.startswith("researchpkg:")
    assert package.research_opportunity_id == opportunity.research_opportunity_id


def test_missing_seed_evidence_stays_in_evidence_queue() -> None:
    opportunity = build_research_opportunity(
        _graph(), [_artifact("paper:neighbor")], [], _assessment(),
        as_of_date="2026-08-11",
        taxonomy_version="v2",
        research_question="Question",
        required_observables=["L2_BOOK_SNAPSHOT"],
        producer_revision="test-rev",
        config_hash="cfg",
    )
    assert opportunity.status == "EVIDENCE_QUEUE"
    with pytest.raises(ValueError, match="only READY"):
        build_factor_research_package(
            opportunity,
            target_track="intraday_hf",
            data_contract_id="intraday_hf_v1",
            data_contract_hash="datahash",
            field_registry_version="fields-v1",
            operator_registry_version="ops-v1",
            memory_snapshot_id="memory-v1",
            research_budget={},
            selection_trace={},
        )
