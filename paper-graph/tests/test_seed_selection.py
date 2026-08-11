from paper_graph.seed_selection import select_seed_manifests


def _row(index: int, *, approved: bool, arxiv: bool = False) -> dict:
    return {
        "openalex_id": f"W{index}",
        "canonical_paper_id": f"openalex:W{index}",
        "arxiv_id": f"2401.{index:05d}" if arxiv else None,
        "title": f"Stock Market Trading Strategy {index}",
        "type": "article",
        "finance_status": "accepted" if approved else "review",
        "finance_acceptance_score": 8 - index,
        "finance_negative_contexts": [],
        "research_value_tier": "high" if approved else "unknown",
        "research_value_score": 8 if approved else 0,
        "graph_seed_eligible": approved,
        "referenced_works_count": 2,
        "cited_by_count": index,
        "quant_match": {"quant_score": 5},
    }


def test_seed_selection_separates_approved_and_expansion() -> None:
    rows = [_row(1, approved=True, arxiv=True)] + [
        _row(index, approved=False, arxiv=index == 2) for index in range(2, 6)
    ]
    graph, digest = select_seed_manifests(rows, graph_target=3, digest_target=2)
    assert len(graph) == 3
    assert graph[0]["selection_status"] == "approved"
    assert sum(row["selection_status"] == "expansion_candidate" for row in graph) == 2
    assert len(digest) == 2
    assert digest[0]["selection_status"] == "approved"
