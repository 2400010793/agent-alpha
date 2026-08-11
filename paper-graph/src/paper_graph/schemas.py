"""Stable JSON response shapes consumed by the future web page."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class GraphNode:
    id: str
    title: str
    abstract: str = ""
    year: int | None = None
    authors: list[str] = field(default_factory=list)
    citation_count: int = 0
    global_impact: float = 0.0
    is_seed: bool = False
    role: str = "related"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    source: str
    target: str
    relation: str
    weight: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphStats:
    node_count: int
    citation_edge_count: int
    similarity_edge_count: int


@dataclass
class GraphResponse:
    seed: str
    seed_title: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    stats: GraphStats

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)