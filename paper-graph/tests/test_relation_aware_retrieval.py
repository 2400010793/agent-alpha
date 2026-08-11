from paper_graph.models import PaperEdge
from paper_graph.relation_aware_retrieval import (
    citation_evolution_paths,
    verified_pairwise_relations,
)


def test_evolution_path_reverses_citation_direction() -> None:
    nodes = [
        {"id": "old", "year": 2010, "citation_count": 100},
        {"id": "middle", "year": 2018, "citation_count": 50},
        {"id": "new", "year": 2025, "citation_count": 10},
    ]
    edges = [
        PaperEdge("middle", "old", "CITES"),
        PaperEdge("new", "middle", "CITES"),
    ]
    paths = citation_evolution_paths(
        nodes, edges, start_paper_id="old", end_paper_id="new"
    )
    assert paths[0].paper_ids == ("old", "middle", "new")
    assert paths[0].requires_coherence_review is True


def test_similarity_edge_cannot_create_evolution_path() -> None:
    nodes = [{"id": "old", "year": 2010}, {"id": "new", "year": 2025}]
    edges = [PaperEdge("old", "new", "EMBEDDING_SIMILAR_TO", weight=0.99)]
    assert citation_evolution_paths(
        nodes, edges, start_paper_id="old", end_paper_id="new"
    ) == []


def test_pairwise_retrieval_excludes_unverified_relations() -> None:
    verified = PaperEdge(
        "new", "old", "SUPPORTS", 0.9,
        {"review_status": "verified", "relation_id": "r1"},
    )
    proposed = PaperEdge(
        "other", "old", "CONTRADICTS", 0.8,
        {"review_status": "proposed", "relation_id": "r2"},
    )
    assert verified_pairwise_relations([proposed, verified], "old") == [verified]
