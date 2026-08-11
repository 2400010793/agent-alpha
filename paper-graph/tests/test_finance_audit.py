from paper_graph.finance_audit import FINANCE_AUDIT_VERSION, audit_finance_context
from paper_graph.openalex_snapshot import classify_quant_work


def _audit(work: dict):
    return audit_finance_context(work, classify_quant_work(work))


def _abstract(text: str) -> dict[str, list[int]]:
    return {token: [index] for index, token in enumerate(text.split())}


def test_accepts_explicit_market_microstructure_context() -> None:
    decision = _audit({"title": "Order Flow and Price Impact in Limit Order Books"})
    assert decision.status == "accepted"
    assert "order flow" in decision.finance_anchors
    assert decision.audit_version == FINANCE_AUDIT_VERSION


def test_generic_machine_learning_without_finance_anchor_is_review() -> None:
    decision = _audit({"title": "Machine Learning for Weather Forecasting"})
    assert decision.status == "rejected"
    assert "weather forecasting" in decision.negative_contexts


def test_intraday_without_strong_finance_anchor_is_review() -> None:
    decision = _audit({"title": "Intraday Patterns in Urban Traffic Flow"})
    assert decision.status == "rejected"


def test_corporate_liquidity_does_not_auto_accept() -> None:
    decision = _audit({"title": "Corporate Liquidity and Cash Holdings"})
    assert decision.status == "review"
    assert any(reason.startswith("ambiguous_finance_context:") for reason in decision.reasons)


def test_market_liquidity_is_accepted_with_explicit_market_phrase() -> None:
    decision = _audit({
        "title": "Market Liquidity and Volatility Shocks",
        "referenced_works_count": 1,
    })
    assert decision.status == "accepted"
    assert "market liquidity" in decision.finance_anchors


def test_abstract_finance_anchor_can_support_generic_title_match() -> None:
    work = {
        "title": "Machine Learning",
        "abstract_inverted_index": {
            "limit": [0],
            "order": [1],
            "book": [2],
            "prediction": [3],
        },
    }
    decision = _audit(work)
    assert decision.status == "review"
    assert "limit order book" in decision.finance_anchors


def test_audit_does_not_change_retrieval_membership() -> None:
    work = {"title": "Machine Learning for Medical Imaging"}
    match = classify_quant_work(work)
    decision = audit_finance_context(work, match)
    assert match["is_quant_candidate"] is True
    assert decision.status == "rejected"


def test_openalex_metadata_only_market_liquidity_cannot_auto_accept() -> None:
    work = {
        "title": "Evaluating the Drivers of Airlines Profitability",
        "keywords": [{"display_name": "Market liquidity"}],
    }
    decision = _audit(work)
    assert decision.status == "review"
    assert decision.reasons == ("ambiguous_finance_context:profitability",)
    assert decision.acceptance_score == 0


def test_metadata_only_neutral_title_is_review() -> None:
    work = {
        "title": "An Empirical Investigation",
        "topics": [{"display_name": "Market liquidity"}],
    }
    decision = _audit(work)
    assert decision.status == "review"
    assert decision.reasons == ("metadata_only_keyword_or_topic_match",)
    assert decision.acceptance_score == 0


def test_generic_match_with_finance_context_only_in_abstract_stays_review() -> None:
    work = {
        "title": "E-Commerce Data Analysis and Visualization Using Python",
        "abstract_inverted_index": _abstract("machine learning stock market examples"),
    }
    decision = _audit(work)
    assert decision.status == "review"
    assert decision.acceptance_score < 5


def test_generic_machine_learning_requires_title_market_context() -> None:
    decision = _audit({
        "title": "Machine Learning Trading Strategy for the Stock Market",
        "referenced_works_count": 1,
    })
    assert decision.status == "accepted"
    assert decision.acceptance_score >= 5
    assert decision.authored_match_fields == ("title",)


def test_negative_energy_context_blocks_incidental_intraday_volatility() -> None:
    work = {
        "title": "Battery Storage Optimization",
        "abstract_inverted_index": _abstract("intraday volatility in power grid energy dispatch"),
    }
    assert _audit(work).status == "rejected"


def test_direct_order_flow_title_is_high_confidence() -> None:
    decision = _audit({"title": "Multi-level Order Flow Imbalance in a Limit Order Book"})
    assert decision.status == "accepted"
    assert decision.acceptance_score >= 6


def test_direct_phrase_only_in_abstract_never_auto_accepts() -> None:
    work = {
        "title": "Tiny LSTM Forecasting via Low Order Chebyshev Expansion",
        "abstract_inverted_index": _abstract("we predict an order book with machine learning"),
    }
    decision = _audit(work)
    assert decision.status == "review"


def test_broad_market_making_title_stays_review() -> None:
    decision = _audit({
        "title": "Respatialising Finance: Power, Politics and Offshore Renminbi Market Making",
    })
    assert decision.status == "review"


def test_non_research_work_type_is_rejected() -> None:
    decision = _audit({
        "type": "book",
        "title": "Algorithmic Trading via Machine Learning",
    })
    assert decision.status == "rejected"
    assert decision.reasons == ("non_research_work_type:book",)


def test_broad_finance_title_without_abstract_or_citations_stays_review() -> None:
    decision = _audit({
        "type": "preprint",
        "title": "Trading Volume as a Signal in the Stock Market",
    })
    assert decision.status == "review"
    assert decision.reasons == ("insufficient_local_evidence_for_auto_accept",)


def test_high_precision_title_can_pass_without_abstract() -> None:
    decision = _audit({
        "type": "preprint",
        "title": "Order Flow Imbalance in a Limit Order Book",
    })
    assert decision.status == "accepted"
