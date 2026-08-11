"""Evidence-based literature relation verification."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .models import PaperEdge


def verified_reference_edges(papers: Iterable[Mapping[str, Any]]) -> list[PaperEdge]:
    """Create only edges explicitly present in a paper's provider references.

    Search relevance, recommendations, author overlap, and embedding scores are
    deliberately ignored. The target must be another paper in the supplied
    candidate set and the source must carry a non-synthetic references list.
    """
    records = {str(paper.get("id")): paper for paper in papers if paper.get("id")}
    edges: dict[tuple[str, str, str], PaperEdge] = {}
    for source, paper in records.items():
        metadata = paper.get("metadata")
        if not isinstance(metadata, Mapping) or metadata.get("synthetic") is True:
            continue
        references = metadata.get("references")
        if not isinstance(references, (list, tuple, set)):
            continue
        reference_ids = {str(value) for value in references}
        for target in sorted(reference_ids & records.keys()):
            if source == target:
                continue
            edge = PaperEdge(
                source,
                target,
                "CITES",
                1.0,
                {
                    "verified": True,
                    "provider": metadata.get("provider"),
                    "evidence": "references",
                },
            )
            edges[edge.key()] = edge
    return list(edges.values())
