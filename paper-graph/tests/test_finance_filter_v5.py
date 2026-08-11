from paper_graph.finance_filter_v5 import (
    FINANCE_AUDIT_VERSION,
    RESEARCH_VALUE_VERSION,
    assess_research_value_v2,
    audit_finance_context_v5,
    classify_quant_work_v2,
)


def _abstract(text: str) -> dict[str, list[int]]:
    return {token: [index] for index, token in enumerate(text.split())}


def _audit(work: dict):
    match = classify_quant_work_v2(work)
    return match, audit_finance_context_v5(work, match)


def test_unpaired_machine_learning_is_not_a_v5_candidate() -> None:
    match, decision = _audit({"title": "Machine Learning for Radio Source Identification"})
    assert match["retrieval_tier"] == "weak"
    assert match["is_quant_candidate"] is False
    assert decision.status == "rejected"


def test_material_microstructure_is_not_a_v5_candidate() -> None:
    match, decision = _audit({"title": "Microstructure Evolution in Titanium Alloys"})
    assert match["retrieval_tier"] == "weak"
    assert decision.status == "rejected"


def test_method_plus_stock_market_context_is_retained_and_accepted() -> None:
    work = {"type": "article", "title": "Machine Learning Trading Strategies for the Stock Market"}
    match, decision = _audit(work)
    assert match["retrieval_tier"] == "contextual"
    assert match["is_quant_candidate"] is True
    assert decision.status == "accepted"
    assert decision.audit_version == FINANCE_AUDIT_VERSION


def test_reinforcement_learning_portfolio_title_is_discovered() -> None:
    work = {
        "type": "article",
        "title": "Deep Reinforcement Learning for Investment Portfolio Management",
        "abstract_inverted_index": _abstract("we evaluate an out of sample investment policy"),
    }
    match, decision = _audit(work)
    assert match["is_quant_candidate"] is True
    assert "reinforcement learning" in match["matched_title_method_terms"]
    assert decision.status == "accepted"


def test_chinese_limit_order_book_alias_is_high_precision() -> None:
    match, decision = _audit({"type": "article", "title": "基于限价订单簿的订单流不平衡研究"})
    assert "limit order book" in match["matched_title_terms"]
    assert "order flow imbalance" in match["matched_title_terms"]
    assert decision.status == "accepted"


def test_metadata_only_direct_term_stays_review_and_low_priority() -> None:
    work = {
        "type": "article",
        "title": "An Empirical Investigation",
        "keywords": [{"display_name": "Order flow"}],
    }
    match, decision = _audit(work)
    assert match["retrieval_tier"] == "metadata"
    assert decision.status == "review"
    assert decision.review_priority == "low"


def test_new_core_preprint_is_not_penalized_for_zero_citations() -> None:
    work = {"type": "preprint", "title": "Price Discovery from Limit Order Book Dynamics"}
    match, decision = _audit(work)
    value = assess_research_value_v2(work, decision)
    assert decision.status == "accepted"
    assert value.tier in {"high", "medium"}
    assert value.version == RESEARCH_VALUE_VERSION


def test_basic_stock_prediction_remains_low_value() -> None:
    work = {
        "type": "article",
        "title": "Stock Price Prediction System with Improved Neural Network",
        "abstract_inverted_index": _abstract("we compare a machine learning model"),
    }
    _, decision = _audit(work)
    value = assess_research_value_v2(work, decision)
    assert decision.status == "accepted"
    assert value.tier == "low"


def test_lstm_finance_title_needs_no_ai_relevance_review_but_stays_low_value() -> None:
    work = {
        "type": "article",
        "title": "Stock Price Prediction System with Improved LSTM",
    }
    match, decision = _audit(work)
    value = assess_research_value_v2(work, decision)
    assert match["retrieval_tier"] == "contextual"
    assert decision.status == "accepted"
    assert value.tier == "low"
