from paper_graph.graph_builder import PaperGraphBuilder


def test_builder_keeps_discovery_direction_and_separates_related_edges():
    papers = [
        {"id": "a", "title": "A", "authors": ["same"], "metadata": {"references": ["b"]}},
        {"id": "b", "title": "B", "authors": ["same"], "metadata": {}},
        {"id": "c", "title": "C", "authors": [], "metadata": {"discovered_from": "a", "discovered_via": "related"}},
    ]

    response = PaperGraphBuilder().response(papers, seed="a", top_k=2, minimum_embedding_score=0.99)
    relations = {(edge["source"], edge["target"], edge["relation"]) for edge in response["edges"]}

    assert ("a", "b", "CITES") in relations
    assert all(edge["relation"] != "CITES" or edge["metadata"].get("direct") is not False for edge in response["edges"])
    assert not any(edge["source"] == "a" and edge["target"] == "c" and edge["relation"] == "CITES" for edge in response["edges"])
    assert response["nodes"][0]["is_seed"] is True
