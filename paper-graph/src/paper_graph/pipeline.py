"""Small local pipeline entry points; external API access is intentionally absent."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from .citation_similarity import top_k_citation_edges
from .graph import deduplicate_edges
from .models import PaperEdge
from .similarity import top_k_embedding_edges


def build_edges(
    citations: Iterable[tuple[Mapping[str, object], Mapping[str, object]]],
    embeddings: Mapping[str, Sequence[float]] | None = None,
    references: Mapping[str, set[str]] | None = None,
    cited_by: Mapping[str, set[str]] | None = None,
    *,
    top_k: int = 20,
) -> list[PaperEdge]:
    """Build the two supported edge types from already-local input data."""
    del citations
    edges: list[PaperEdge] = []
    if references is not None and cited_by is not None:
        edges.extend(top_k_citation_edges(references, cited_by, k=top_k))
    if embeddings:
        edges.extend(top_k_embedding_edges(embeddings, k=top_k))
    return deduplicate_edges(edges)