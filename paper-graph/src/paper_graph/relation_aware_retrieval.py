"""Relation-aware retrieval primitives for bounded scientific graphs.

Paper parsing and citation-context extraction are upstream responsibilities.
This module consumes normalized nodes and edges to retrieve verified pairwise
relations and candidate citation-evolution paths.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .models import EPISTEMIC_EDGE_TYPES, PaperEdge


@dataclass(frozen=True)
class EvolutionPathCandidateV1:
    start_paper_id: str
    end_paper_id: str
    paper_ids: tuple[str, ...]
    citation_edge_count: int
    cumulative_impact: float
    path_score: float
    requires_coherence_review: bool = True
    schema_version: str = "evolution_path_candidate_v1"


def verified_pairwise_relations(
    edges: Iterable[PaperEdge], paper_id: str
) -> list[PaperEdge]:
    """Return verified epistemic relations touching one paper."""

    return sorted(
        (
            edge
            for edge in edges
            if edge.relation in EPISTEMIC_EDGE_TYPES
            and edge.metadata.get("review_status") == "verified"
            and paper_id in {edge.source, edge.target}
        ),
        key=lambda edge: (-(edge.weight or 0.0), edge.relation, edge.source, edge.target),
    )


def citation_evolution_paths(
    nodes: Iterable[Mapping[str, Any]],
    edges: Iterable[PaperEdge],
    *,
    start_paper_id: str,
    end_paper_id: str,
    max_hops: int = 6,
    max_paths: int = 20,
) -> list[EvolutionPathCandidateV1]:
    """Find bounded older-to-newer paths by reversing explicit ``CITES`` edges.

    ``CITES`` is stored as newer/citing -> older/cited.  Scientific evolution
    is returned in the intuitive foundation -> descendant order.  Similarity
    and LLM-inferred relations never create path connectivity.
    """

    if max_hops < 1 or max_paths < 1:
        raise ValueError("max_hops and max_paths must be positive")
    records = {str(node.get("id")): node for node in nodes if node.get("id")}
    if start_paper_id not in records or end_paper_id not in records:
        raise ValueError("path endpoints must exist in the bounded graph")
    adjacency: dict[str, set[str]] = {paper_id: set() for paper_id in records}
    for edge in edges:
        if edge.relation != "CITES":
            continue
        if edge.source in records and edge.target in records and edge.source != edge.target:
            adjacency[edge.target].add(edge.source)

    candidates: list[tuple[str, ...]] = []
    queue = deque([(start_paper_id,)])
    while queue and len(candidates) < max_paths * 10:
        path = queue.popleft()
        if len(path) - 1 >= max_hops:
            continue
        current = path[-1]
        for descendant in sorted(adjacency.get(current, ())):
            if descendant in path:
                continue
            current_year = records[current].get("year")
            descendant_year = records[descendant].get("year")
            if (
                isinstance(current_year, int)
                and isinstance(descendant_year, int)
                and descendant_year < current_year
            ):
                continue
            child = (*path, descendant)
            if descendant == end_paper_id:
                candidates.append(child)
            else:
                queue.append(child)

    result = []
    for path in candidates:
        impact = sum(
            math.log1p(max(0, int(records[paper_id].get("citation_count") or 0)))
            for paper_id in path
        )
        # Prefer recognized, shorter trajectories without allowing citation
        # count to turn an incoherent path into a verified scientific lineage.
        score = impact / max(1, len(path)) + 1.0 / max(1, len(path) - 1)
        result.append(EvolutionPathCandidateV1(
            start_paper_id=start_paper_id,
            end_paper_id=end_paper_id,
            paper_ids=path,
            citation_edge_count=len(path) - 1,
            cumulative_impact=round(impact, 6),
            path_score=round(score, 6),
        ))
    return sorted(result, key=lambda item: (-item.path_score, item.paper_ids))[:max_paths]


__all__ = [
    "EvolutionPathCandidateV1",
    "citation_evolution_paths",
    "verified_pairwise_relations",
]
