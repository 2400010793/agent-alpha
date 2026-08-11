from paper_graph.graph_value import (
    GraphValueFeaturesV1,
    ResearchPortfolioController,
    assess_graph_value,
)


def _features(graph_id: str, **overrides) -> GraphValueFeaturesV1:
    values = {
        "graph_id": graph_id,
        "topic_ids": ("order_flow_imbalance",),
        "target_track": "intraday_hf",
        "data_contract_id": "intraday_hf_v1",
        "evidence_readiness": 0.9,
        "data_feasibility": 0.9,
        "direct_observability": 0.9,
        "graph_coherence": 0.8,
        "novelty": 0.8,
        "claim_relation_coverage": 0.6,
        "contradiction_density": 0.0,
        "downstream_utility": 0.9,
        "redundancy": 0.1,
        "estimated_cost": 0.2,
    }
    values.update(overrides)
    return GraphValueFeaturesV1(**values)


def test_feasible_evidence_ready_graph_routes_to_factor_research() -> None:
    assessment = assess_graph_value(_features("graph:ofi"))
    assert assessment.priority_tier == "high"
    assert assessment.recommended_action == "RUN_FACTOR_RESEARCH"
    assert assessment.assessment_id.startswith("graphvalue:")


def test_no_data_is_a_hard_defer_even_with_novel_graph() -> None:
    assessment = assess_graph_value(_features(
        "graph:options", data_feasibility=0.0, novelty=1.0
    ))
    assert assessment.priority_tier == "defer"
    assert assessment.recommended_action == "NEEDS_DATA"


def test_comparable_disagreement_routes_to_contradiction_resolution() -> None:
    assessment = assess_graph_value(_features(
        "graph:disagreement",
        contradiction_density=0.3,
        claim_relation_coverage=0.7,
    ))
    assert assessment.recommended_action == "RESOLVE_CONTRADICTION"


def test_portfolio_controller_respects_cost_and_topic_limits() -> None:
    first = _features("graph:one", estimated_cost=0.4)
    second = _features("graph:two", estimated_cost=0.4)
    third = _features("graph:three", topic_ids=("realized_volatility",), estimated_cost=0.4)
    pairs = [(item, assess_graph_value(item)) for item in (first, second, third)]
    selected = ResearchPortfolioController().select(
        pairs, max_graphs=3, cost_budget=0.8, max_per_primary_topic=1
    )
    assert sum(item.selected for item in selected) == 2
    assert any(item.selection_reason == "primary_topic_diversity_limit" for item in selected)
