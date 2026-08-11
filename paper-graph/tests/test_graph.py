import pytest

from paper_graph.graph import citation_edge, deduplicate_edges, validate_edges


def test_citation_is_directed_and_provenance_is_retained() -> None:
    edge = citation_edge(
        {"arxiv": "2401.00001v2"}, {"doi": "https://doi.org/10.1000/ABC"}, source="s2"
    )
    assert edge.source == "arxiv:2401.00001"
    assert edge.target == "doi:10.1000/abc"
    assert edge.relation == "CITATION_SIMILAR_TO"
    assert edge.metadata["source"] == "s2"


def test_duplicate_citation_edges_are_removed() -> None:
    edge = citation_edge({"arxiv": "2401.00001"}, {"arxiv": "2401.00002"})
    assert len(deduplicate_edges([edge, edge])) == 1


def test_self_similarity_is_rejected() -> None:
    with pytest.raises(ValueError, match="cite itself"):
        citation_edge({"arxiv": "2401.00001"}, {"arxiv": "2401.00001v2"})


def test_citation_similarity_validation_requires_weight() -> None:
    edge = citation_edge({"arxiv": "2401.00001"}, {"arxiv": "2401.00002"})
    invalid = edge.__class__(edge.source, edge.target, edge.relation)
    assert validate_edges([invalid])