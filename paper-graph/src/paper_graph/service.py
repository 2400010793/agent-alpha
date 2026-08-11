"""Seed-centered graph service for the page API."""

from __future__ import annotations

from .schemas import GraphEdge, GraphNode, GraphResponse, GraphStats
from .storage import PaperStore


class PaperGraphService:
    def __init__(self, store: PaperStore) -> None:
        self.store = store

    def search(self, query: str, limit: int = 20) -> list[dict]:
        return self.store.search(query, limit)

    def graph(self, paper_id: str, limit: int = 40) -> GraphResponse:
        seed = self.store.paper(paper_id)
        if seed is None:
            raise KeyError(paper_id)
        related_ids = {paper_id}
        for edge in self.store.edges:
            if edge.source == paper_id or edge.target == paper_id:
                related_ids.update((edge.source, edge.target))
        # Keep the seed and make the ordering deterministic for API clients.
        related_ids = {paper_id} | set(sorted(related_ids - {paper_id})[: max(0, limit - 1)])
        papers = {node_id: self.store.paper(node_id) or {"id": node_id, "title": node_id}
                  for node_id in related_ids}
        nodes = []
        for node_id in related_ids:
            paper = papers[node_id]
            role = "seed"
            role_metadata = {"role_reason": "seed"}
            if node_id != paper_id:
                year = paper.get("year")
                evidence = next((edge for edge in self.store.edges
                                 if edge.relation == "CITES"
                                 and not (edge.metadata or {}).get("synthetic")
                                 and ((edge.source == paper_id and edge.target == node_id)
                                      or (edge.source == node_id and edge.target == paper_id))), None)
                seed_year = papers[paper_id].get("year")
                if isinstance(year, int) and isinstance(seed_year, int) and evidence:
                    if evidence.source == paper_id and year < seed_year:
                        role = "prior"
                        role_metadata = {"role_reason": "seed_cites", "role_evidence": "direct_citation"}
                    elif evidence.target == paper_id and year > seed_year:
                        role = "derivative"
                        role_metadata = {"role_reason": "cites_seed", "role_evidence": "direct_citation"}
                    else:
                        role = "related"
                        role_metadata = {"role_reason": "year_direction_mismatch"}
                else:
                    role_metadata = {"role_reason": "no_verified_directional_citation"}
            nodes.append(GraphNode(
                id=node_id, title=str(paper.get("title", "")), year=paper.get("year"),
                authors=list(paper.get("authors", [])), citation_count=int(paper.get("citation_count", 0)),
                global_impact=float(paper.get("global_impact", 0.0)), is_seed=node_id == paper_id,
                role=role,
                metadata={**(paper.get("metadata") or {}), **role_metadata},
            ))
        edges = [GraphEdge(e.source, e.target, e.relation, e.weight, e.metadata)
                 for e in self.store.edges if e.source in related_ids and e.target in related_ids]
        return GraphResponse(
            seed=paper_id, seed_title=str(seed.get("title", "")), nodes=nodes, edges=edges,
            stats=GraphStats(len(nodes), sum(e.relation == "CITATION_SIMILAR_TO" for e in edges),
                             sum(e.relation == "EMBEDDING_SIMILAR_TO" for e in edges)),
        )