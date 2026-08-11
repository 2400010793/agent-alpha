from paper_graph.finance_audit import audit_finance_context
from paper_graph.openalex_snapshot import classify_quant_work
from paper_graph.research_value import RESEARCH_VALUE_VERSION, assess_research_value


def _abstract(text: str) -> dict[str, list[int]]:
    return {token: [index] for index, token in enumerate(text.split())}


def _value(work: dict):
    finance = audit_finance_context(work, classify_quant_work(work))
    return assess_research_value(work, finance)


def test_order_book_research_is_high_value() -> None:
    decision = _value({
        "type": "article",
        "title": "Multi-level Order Flow Imbalance in a Limit Order Book",
        "abstract_inverted_index": _abstract("out of sample price impact evidence"),
        "referenced_works_count": 20,
    })
    assert decision.tier == "high"
    assert decision.score >= 5
    assert decision.version == RESEARCH_VALUE_VERSION


def test_basic_stock_prediction_is_low_value() -> None:
    decision = _value({
        "type": "article",
        "title": "Stock Price Prediction System with Improved LSTM",
        "abstract_inverted_index": _abstract("machine learning stock market"),
    })
    assert decision.tier == "low"


def test_book_is_excluded_even_when_financial() -> None:
    decision = _value({
        "type": "book",
        "title": "Algorithmic Trading via Machine Learning",
    })
    assert decision.tier == "exclude"
