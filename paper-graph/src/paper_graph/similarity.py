"""Dependency-free embedding similarity helpers."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .models import PaperEdge


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Calculate cosine similarity and reject invalid vector dimensions."""
    if not left or len(left) != len(right):
        raise ValueError("vectors must be non-empty and have equal dimensions")
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    if denominator == 0:
        raise ValueError("zero vectors do not have a cosine similarity")
    return sum(a * b for a, b in zip(left, right)) / denominator


def top_k_embedding_edges(
    embeddings: Mapping[str, Sequence[float]], *, k: int = 20, minimum_score: float = 0.0
) -> list[PaperEdge]:
    """Build undirected top-k embedding edges, keeping each pair once."""
    if k < 1:
        raise ValueError("k must be positive")
    scores: dict[tuple[str, str], float] = {}
    paper_ids = list(embeddings)
    for index, source in enumerate(paper_ids):
        for target in paper_ids[index + 1 :]:
            score = cosine_similarity(embeddings[source], embeddings[target])
            if score >= minimum_score:
                scores[(source, target)] = score

    selected: list[PaperEdge] = []
    by_source: dict[str, list[tuple[float, str]]] = {paper_id: [] for paper_id in paper_ids}
    for (source, target), score in scores.items():
        by_source[source].append((score, target))
        by_source[target].append((score, source))
    selected_pairs: set[tuple[str, str]] = set()
    for source, candidates in by_source.items():
        for score, target in sorted(candidates, reverse=True)[:k]:
            pair = tuple(sorted((source, target)))
            if pair in selected_pairs:
                continue
            selected_pairs.add(pair)
            selected.append(
                PaperEdge(
                    source=pair[0],
                    target=pair[1],
                    relation="EMBEDDING_SIMILAR_TO",
                    weight=score,
                    metadata={"metric": "cosine", "top_k": k},
                )
            )
    return sorted(selected, key=lambda edge: edge.weight or 0.0, reverse=True)


def top_k_author_edges(papers: Mapping[str, Mapping[str, object]], *, k: int = 4) -> list[PaperEdge]:
    """Build weighted edges between papers that share one or more authors."""
    by_author: dict[str, set[str]] = {}
    for paper_id, paper in papers.items():
        author_ids = (paper.get("metadata") or {}).get("author_ids", []) if isinstance(paper.get("metadata"), Mapping) else []
        authors = author_ids or paper.get("authors", [])
        if not isinstance(authors, (list, tuple)):
            continue
        for author in authors:
            key = str(author).strip().casefold()
            if key:
                by_author.setdefault(key, set()).add(paper_id)
    scores: dict[tuple[str, str], float] = {}
    for paper_ids in by_author.values():
        ids = sorted(paper_ids)
        for index, source in enumerate(ids):
            for target in ids[index + 1:]:
                scores[(source, target)] = scores.get((source, target), 0.0) + 1.0
    limit = k * max(len(papers), 1)
    return [PaperEdge(source, target, "AUTHOR_SHARED_BY", score, {"shared_authors": int(score)})
            for (source, target), score in sorted(scores.items(), key=lambda item: -item[1])[:limit]]