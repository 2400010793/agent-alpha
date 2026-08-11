from paper_graph.verification import verified_reference_edges


def test_verified_edges_require_explicit_references_and_preserve_direction():
    papers = [
        {"id": "a", "metadata": {"provider": "openalex", "references": ["b"]}},
        {"id": "b", "metadata": {"provider": "openalex", "references": []}},
        {"id": "c", "metadata": {"provider": "openalex", "references": ["b"], "synthetic": True}},
    ]
    edges = verified_reference_edges(papers)
    assert [(edge.source, edge.target, edge.relation) for edge in edges] == [("a", "b", "CITES")]
    assert edges[0].metadata["verified"] is True
    assert edges[0].metadata["evidence"] == "references"