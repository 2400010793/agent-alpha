"""Data models for the first Paper Graph milestone."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class PaperId:
    """A canonical paper identifier with optional provider identifiers."""

    canonical: str
    arxiv: str | None = None
    doi: str | None = None
    openalex: str | None = None
    semantic_scholar: str | None = None


@dataclass(frozen=True)
class PaperNode:
    """A paper node suitable for JSONL serialization."""

    paper_id: PaperId
    title: str = ""
    year: int | None = None
    authors: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


EdgeType = Literal[
    "CITES",
    "CITED_BY",
    "CITATION_SIMILAR_TO",
    "EMBEDDING_SIMILAR_TO",
    "AUTHOR_SHARED_BY",
    "SUPPORTS",
    "CONTRADICTS",
    "REPLICATES",
    "FAILS_TO_REPLICATE",
    "REFINES",
    "QUALIFIES",
    "EXTENDS",
    "USES_METHOD_FROM",
    "BOUNDARY_CONDITION",
]


EPISTEMIC_EDGE_TYPES = frozenset({
    "SUPPORTS",
    "CONTRADICTS",
    "REPLICATES",
    "FAILS_TO_REPLICATE",
    "REFINES",
    "QUALIFIES",
    "EXTENDS",
    "USES_METHOD_FROM",
    "BOUNDARY_CONDITION",
})


@dataclass(frozen=True)
class PaperEdge:
    """A weighted citation-structure or embedding-similarity relation.

    ``CITATION_SIMILAR_TO`` combines co-citation and bibliographic coupling;
    it is not a direct citation edge.
    """

    source: str
    target: str
    relation: EdgeType
    weight: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def key(self) -> tuple[str, str, EdgeType]:
        """Return a stable key used for de-duplication."""
        if self.relation in {"CITATION_SIMILAR_TO", "EMBEDDING_SIMILAR_TO", "AUTHOR_SHARED_BY"}:
            return (*sorted((self.source, self.target)), self.relation)
        return (self.source, self.target, self.relation)
