import pytest

from paper_graph.citation_similarity import citation_similarity, top_k_citation_edges


def test_components_measure_coupling_and_cocitation() -> None:
    combined, bibliographic, cocitation = citation_similarity(
        {"references": {"r1", "r2"}, "cited_by": {"p1", "p2"}},
        {"references": {"r1", "r3"}, "cited_by": {"p1", "p3"}},
    )
    assert bibliographic == pytest.approx(0.5)
    assert cocitation == pytest.approx(0.5)
    assert combined == pytest.approx(0.5)


def test_top_k_structural_edges_store_component_scores() -> None:
    edges = top_k_citation_edges(
        {"a": {"r1"}, "b": {"r1"}, "c": {"r2"}},
        {"a": {"p1"}, "b": {"p1"}, "c": {"p2"}},
        k=1, minimum_score=0.5,
    )
    assert len(edges) == 1
    assert edges[0].relation == "CITATION_SIMILAR_TO"
    assert edges[0].weight == pytest.approx(1.0)
    assert edges[0].metadata["method"] == "co_citation_and_bibliographic_coupling"