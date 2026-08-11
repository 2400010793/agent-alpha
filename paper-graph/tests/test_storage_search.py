from paper_graph.models import PaperEdge
from paper_graph.storage import PaperStore


def store() -> PaperStore:
    return PaperStore([
        {"id": "p-vol", "title": "Volatility Forecasting", "abstract": "Predict volatility from returns.", "keywords": ["risk", "forecasting"], "authors": ["A"]},
        {"id": "p-keyword", "title": "Asset Risk", "abstract": "A study of risk.", "keywords": ["波动率"], "authors": ["B"]},
        {"id": "p-other", "title": "Momentum", "abstract": "A study of returns.", "keywords": ["factor"], "authors": ["C"]},
    ], [])


def test_search_matches_abstract_and_keywords_with_synonyms() -> None:
    results = {paper["id"] for paper in store().search("波动率")}
    assert results == {"p-vol", "p-keyword"}


def test_search_requires_all_query_terms() -> None:
    assert [paper["id"] for paper in store().search("波动率 预测")] == ["p-vol"]


def test_search_corrects_small_typo() -> None:
    assert [paper["id"] for paper in store().search("volatilty")] == ["p-vol"]


def test_search_prioritizes_title_over_abstract_and_keywords() -> None:
    assert [paper["id"] for paper in store().search("risk")] == ["p-keyword", "p-vol"]