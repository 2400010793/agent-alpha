"""Construction and validation of the two-layer paper graph."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .models import EPISTEMIC_EDGE_TYPES, PaperEdge
from .normalize import canonical_paper_id


def citation_edge(
    citing: Mapping[str, Any], cited: Mapping[str, Any], *, source: str = "unknown"
) -> PaperEdge:
    """Create a canonical citation-structure similarity edge."""
    source_id = canonical_paper_id(**_identifiers(citing))
    target_id = canonical_paper_id(**_identifiers(cited))
    if source_id == target_id:
        raise ValueError("a paper cannot cite itself")
    return PaperEdge(
        source=source_id,
        target=target_id,
        relation="CITATION_SIMILAR_TO",
        metadata={"source": source},
    )


def deduplicate_edges(edges: Iterable[PaperEdge]) -> list[PaperEdge]:
    """Remove duplicate relations while preserving first-seen order."""
    result: list[PaperEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        key = edge.key()
        if key not in seen:
            seen.add(key)
            result.append(edge)
    return result


def validate_edges(edges: Iterable[PaperEdge]) -> list[str]:
    """Return validation errors without mutating the input."""
    errors: list[str] = []
    for index, edge in enumerate(edges):
        if not edge.source or not edge.target:
            errors.append(f"edge {index}: source and target are required")
        if edge.source == edge.target:
            errors.append(f"edge {index}: self-loop is not allowed")
        if edge.relation == "CITATION_SIMILAR_TO" and edge.weight is None:
            errors.append(f"edge {index}: citation similarity requires a weight")
        if edge.relation == "EMBEDDING_SIMILAR_TO" and edge.weight is None:
            errors.append(f"edge {index}: embedding edge requires a weight")
        if edge.relation in EPISTEMIC_EDGE_TYPES:
            required = (
                "relation_id",
                "source_claim_id",
                "target_claim_id",
                "source_evidence_ids",
                "target_evidence_ids",
                "scope_alignment",
                "review_status",
            )
            missing = [name for name in required if not edge.metadata.get(name)]
            if missing:
                errors.append(
                    f"edge {index}: epistemic relation missing metadata: {','.join(missing)}"
                )
            if edge.metadata.get("review_status") != "verified":
                errors.append(f"edge {index}: epistemic relation must be verified")
    return errors


def _identifiers(record: Mapping[str, Any]) -> dict[str, str | None]:
    """Extract supported identifiers and ignore unrelated metadata fields."""
    return {
        "arxiv": record.get("arxiv"),
        "doi": record.get("doi"),
        "openalex": record.get("openalex"),
        "semantic_scholar": record.get("semantic_scholar"),
    }
