import pytest

from paper_graph.similarity import cosine_similarity, top_k_embedding_edges


def test_cosine_similarity() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_embedding_edges_are_unique_and_weighted() -> None:
    edges = top_k_embedding_edges(
        {"a": [1.0, 0.0], "b": [1.0, 0.0], "c": [0.0, 1.0]}, k=1, minimum_score=0.5
    )
    assert len(edges) == 1
    assert edges[0].relation == "EMBEDDING_SIMILAR_TO"
    assert edges[0].weight == pytest.approx(1.0)