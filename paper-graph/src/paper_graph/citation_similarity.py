"""Connected Papers-inspired co-citation and bibliographic coupling."""

from __future__ import annotations

import math
from collections.abc import Mapping, Set

from .models import PaperEdge


def direct_citation_edges(references: Mapping[str, Set[str]], paper_ids: set[str]) -> list[PaperEdge]:
    """Return directed edges for references that are present in the graph."""
    edges: list[PaperEdge] = []
    for source, targets in references.items():
        for target in targets & paper_ids:
            if source != target:
                edges.append(PaperEdge(source, target, "CITES", 1.0, {"direct": True}))
    return edges


def _cosine_set(left: Set[str], right: Set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / math.sqrt(len(left) * len(right))


def citation_similarity(
    left: Mapping[str, Set[str]], right: Mapping[str, Set[str]], *,
    bibliographic_weight: float = 0.5, cocitation_weight: float = 0.5,
) -> tuple[float, float, float]:
    """Return combined, bibliographic-coupling, and co-citation scores."""
    if bibliographic_weight < 0 or cocitation_weight < 0:
        raise ValueError("similarity weights cannot be negative")
    total = bibliographic_weight + cocitation_weight
    if total == 0:
        raise ValueError("at least one similarity weight must be positive")
    bibliographic = _cosine_set(left.get("references", set()), right.get("references", set()))
    cocitation = _cosine_set(left.get("cited_by", set()), right.get("cited_by", set()))
    combined = (bibliographic_weight * bibliographic + cocitation_weight * cocitation) / total
    return combined, bibliographic, cocitation


def top_k_citation_edges(
    references: Mapping[str, Set[str]], cited_by: Mapping[str, Set[str]], *, k: int = 40,
    bibliographic_weight: float = 0.5, cocitation_weight: float = 0.5,
    minimum_score: float = 0.0,
) -> list[PaperEdge]:
    """Build a bounded undirected citation-structure similarity network."""
    if k < 1:
        raise ValueError("k must be positive")
    paper_ids = sorted(set(references) | set(cited_by))
    scores: dict[tuple[str, str], tuple[float, float, float]] = {}
    for index, source in enumerate(paper_ids):
        for target in paper_ids[index + 1:]:
            score = citation_similarity(
                {"references": references.get(source, set()), "cited_by": cited_by.get(source, set())},
                {"references": references.get(target, set()), "cited_by": cited_by.get(target, set())},
                bibliographic_weight=bibliographic_weight, cocitation_weight=cocitation_weight,
            )
            if score[0] >= minimum_score:
                scores[(source, target)] = score
    neighbours: dict[str, list[tuple[float, str, float, float]]] = {p: [] for p in paper_ids}
    for (source, target), (combined, bibliographic, cocitation) in scores.items():
        neighbours[source].append((combined, target, bibliographic, cocitation))
        neighbours[target].append((combined, source, bibliographic, cocitation))
    selected_pairs: set[tuple[str, str]] = set()
    edges: list[PaperEdge] = []
    for source, candidates in neighbours.items():
        for combined, target, bibliographic, cocitation in sorted(candidates, reverse=True)[:k]:
            pair = tuple(sorted((source, target)))
            if pair in selected_pairs:
                continue
            selected_pairs.add(pair)
            edges.append(PaperEdge(
                source=pair[0], target=pair[1], relation="CITATION_SIMILAR_TO", weight=combined,
                metadata={"method": "co_citation_and_bibliographic_coupling",
                          "bibliographic_coupling": bibliographic, "co_citation": cocitation,
                          "bibliographic_weight": bibliographic_weight,
                          "cocitation_weight": cocitation_weight, "top_k": k},
            ))
    return sorted(edges, key=lambda edge: edge.weight or 0.0, reverse=True)