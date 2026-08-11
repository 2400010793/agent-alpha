"""Shared graph construction for local and externally discovered papers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .citation_similarity import direct_citation_edges, top_k_citation_edges
from .embeddings import HashEmbeddingEncoder
from .models import PaperEdge
from .similarity import top_k_author_edges, top_k_embedding_edges


class PaperGraphBuilder:
    """Build the Paper Graph edge layers from provider-normalized records.

    Records must use ``id`` as their canonical identifier.  Citation edges are
    created only from explicit ``metadata.references`` or discovery direction;
    related/recommendation records never become citations.
    """

    def __init__(self, *, embedding_dimensions: int = 256, encoder: Any | None = None) -> None:
        self.encoder = encoder or HashEmbeddingEncoder(embedding_dimensions)

    @staticmethod
    def _relation_sets(papers: Iterable[Mapping[str, Any]]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        records = {str(paper["id"]): paper for paper in papers}
        references: dict[str, set[str]] = {}
        cited_by: dict[str, set[str]] = {paper_id: set() for paper_id in records}
        for paper_id, paper in records.items():
            metadata = paper.get("metadata")
            metadata = metadata if isinstance(metadata, Mapping) else {}
            # Keep only references whose targets are in this bounded graph.
            # Provider records can contain many references that were not
            # selected as nodes; those must not enlarge the edge universe.
            refs = {str(value) for value in metadata.get("references", [])
                    if value and str(value) in records}
            references[paper_id] = refs
            for target in refs:
                cited_by.setdefault(target, set()).add(paper_id)
            discovered_from = str(metadata.get("discovered_from") or "")
            discovered_via = str(metadata.get("discovered_via") or "")
            if discovered_from in records and discovered_via == "references":
                references[discovered_from] = references.get(discovered_from, set()) | {paper_id}
                cited_by.setdefault(paper_id, set()).add(discovered_from)
            elif discovered_from in records and discovered_via == "citations":
                references[paper_id].add(discovered_from)
                cited_by.setdefault(discovered_from, set()).add(paper_id)
        return references, cited_by

    @staticmethod
    def _normalize_edges(edges: Iterable[PaperEdge]) -> list[PaperEdge]:
        result: dict[tuple[str, str, str], PaperEdge] = {}
        for edge in edges:
            if edge.source == edge.target:
                continue
            result[edge.key()] = edge
        return list(result.values())

    def build(self, papers: Iterable[Mapping[str, Any]], *, top_k: int = 20,
              minimum_embedding_score: float = 0.05,
              minimum_citation_score: float = 0.05) -> tuple[list[dict[str, Any]], list[PaperEdge]]:
        records = [dict(paper) for paper in papers if paper.get("id")]
        by_id = {str(paper["id"]): paper for paper in records}
        references, cited_by = self._relation_sets(records)
        embeddings = self.encoder.encode_papers(records) if records else {}
        direct = direct_citation_edges(references, set(by_id))
        structural = top_k_citation_edges(references, cited_by, k=top_k, minimum_score=minimum_citation_score)
        semantic = top_k_embedding_edges(embeddings, k=top_k, minimum_score=minimum_embedding_score)
        authors = top_k_author_edges(by_id, k=min(top_k, 8))
        return records, self._normalize_edges([*direct, *structural, *semantic, *authors])

    def response(self, papers: Iterable[Mapping[str, Any]], *, seed: str | None = None,
                 seeds: Iterable[str] | None = None,
                 top_k: int = 20, minimum_embedding_score: float = 0.05) -> dict[str, Any]:
        records, edges = self.build(papers, top_k=top_k, minimum_embedding_score=minimum_embedding_score)
        seed_record = next((paper for paper in records if paper.get("id") == seed), None)
        seed_ids = set(seeds or ([seed] if seed else []))
        nodes = []
        for paper in records:
            node = dict(paper)
            node.setdefault("role", "seed" if seed and paper.get("id") == seed else "related")
            node["is_seed"] = str(paper.get("id")) in seed_ids
            if node["is_seed"]:
                node["role"] = "seed"
                node["seed_ids"] = sorted(seed_ids & {str(paper.get("id"))})
            nodes.append(node)
        return {
            "seed": seed,
            "seed_ids": sorted(seed_ids),
            "multi_seed": len(seed_ids) > 1,
            "seed_title": (seed_record or {}).get("title", "") if seed else "",
            "nodes": nodes,
            "edges": [{"source": edge.source, "target": edge.target, "relation": edge.relation,
                       "weight": edge.weight, "metadata": edge.metadata} for edge in edges],
            "stats": {
                "node_count": len(nodes),
                "citation_edge_count": sum(edge.relation in {"CITES", "CITATION_SIMILAR_TO"} for edge in edges),
                "similarity_edge_count": sum(edge.relation == "EMBEDDING_SIMILAR_TO" for edge in edges),
                "author_edge_count": sum(edge.relation == "AUTHOR_SHARED_BY" for edge in edges),
            },
        }
