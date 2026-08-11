"""Optional FastAPI adapter for the frontend contract."""

from __future__ import annotations

from .service import PaperGraphService
from .storage import PaperStore
from .topic_storage import TopicGraphStore
import re
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


def create_app(service: PaperGraphService, topic_graph_root: str | None = None,
               local_semantic_search: Callable[[dict, int], list[dict]] | None = None):
    """Create the HTTP app; FastAPI is optional until the web phase."""
    try:
        from fastapi import FastAPI, HTTPException, Query, Body
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("install the web extra to use the HTTP API") from exc

    app = FastAPI(title="Paper Graph API", version="0.1.0")
    from fastapi.middleware.cors import CORSMiddleware
    from .semantic_scholar import SemanticScholarClient
    from .open_academic import OpenAcademicClient
    from .embeddings import HashEmbeddingEncoder
    from .similarity import top_k_author_edges, top_k_embedding_edges
    from .citation_similarity import direct_citation_edges as provider_direct_citation_edges, top_k_citation_edges
    from .graph_builder import PaperGraphBuilder
    from .schemas import GraphEdge, GraphNode, GraphResponse, GraphStats

    scholar = SemanticScholarClient()
    open_academic = OpenAcademicClient()
    arxiv_lookup_cache: dict[str, dict[str, Any]] = {}
    maps: dict[str, dict] = {}
    topic_store = TopicGraphStore(topic_graph_root) if topic_graph_root else None
    parse_queue_path = Path(topic_graph_root).parent / "paper_parse_queue.jsonl" if topic_graph_root else Path("outputs/paper_parse_queue.jsonl")

    def queue_paper(paper: dict, reason: str = "manual") -> dict:
        """Persist a paper for later full-text/digest parsing without parsing now."""
        parse_queue_path.parent.mkdir(parents=True, exist_ok=True)
        rows: dict[str, dict] = {}
        if parse_queue_path.exists():
            for line in parse_queue_path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("paper_id"):
                    rows[str(row["paper_id"])] = row
        paper_id = str(paper.get("id") or "")
        row = {"paper_id": paper_id, "title": paper.get("title", ""),
               "year": paper.get("year"), "url": paper.get("url"),
               "status": rows.get(paper_id, {}).get("status", "queued"),
               "reason": reason, "metadata": paper.get("metadata") or {}}
        rows[paper_id] = row
        parse_queue_path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rows.values()), encoding="utf-8")
        return row

    def year_config(payload: dict) -> tuple[int | None, float]:
        minimum = payload.get("min_year")
        minimum_year = int(minimum) if minimum not in (None, "", 0) else None
        weight = max(0.0, min(1.0, float(payload.get("year_weight") or 0.0)))
        return minimum_year, weight

    def apply_year_policy(papers: list[dict], seed_ids: set[str], minimum_year: int | None, year_weight: float) -> list[dict]:
        if minimum_year is None and year_weight <= 0:
            return papers
        kept = []
        for paper in papers:
            paper_id = str(paper.get("id"))
            year = paper.get("year")
            if paper_id not in seed_ids and minimum_year is not None and (not isinstance(year, int) or year < minimum_year):
                continue
            metadata = paper.setdefault("metadata", {})
            recency = 0.0 if not isinstance(year, int) else min(1.0, max(0.0, (year - (minimum_year or 2000)) / 20.0))
            metadata["year_score"] = round(recency, 6)
            metadata["year_weight"] = year_weight
            metadata["year_filter"] = minimum_year
            metadata["selection_score"] = float(metadata.get("selection_score") or 0.0) + year_weight * recency * 100.0
            kept.append(paper)
        return kept

    def merge_graph_dicts(graphs: list[dict], seed_ids: list[str]) -> dict:
        nodes = {}
        edges = {}
        all_nodes = []
        all_edges: list[GraphEdge] = []
        for graph_data in graphs:
            for node in graph_data.get("nodes", []):
                node_id = node["id"]
                merged_node = {**node, "is_seed": node_id in seed_ids}
                if node_id in seed_ids:
                    merged_node["seed_ids"] = sorted(set(merged_node.get("seed_ids") or []) | {node_id})
                    merged_node["role"] = "seed"
                if node_id in nodes:
                    existing = nodes[node_id]
                    existing["is_seed"] = existing.get("is_seed", False) or merged_node["is_seed"]
                    if merged_node["is_seed"]:
                        existing["seed_ids"] = sorted(set(existing.get("seed_ids") or []) | set(merged_node.get("seed_ids") or []) | {node_id})
                        existing["role"] = "seed"
                else:
                    nodes[node_id] = merged_node
            for edge in graph_data.get("edges", []):
                source = edge["target"] if edge["relation"] == "CITED_BY" else edge["source"]
                target = edge["source"] if edge["relation"] == "CITED_BY" else edge["target"]
                relation = "CITES" if edge["relation"] == "CITED_BY" else edge["relation"]
                normalized = {**edge, "source": source, "target": target, "relation": relation}
                edges[f'{source}|{target}|{relation}'] = normalized
        all_nodes = list(nodes.values())
        role_info = _classify_roles(all_nodes, set(seed_ids), [GraphEdge(**edge) for edge in edges.values()])
        for node_id, node in nodes.items():
            role, metadata = role_info.get(node_id, ("related", {"role_reason": "unclassified"}))
            node["role"] = role
            node["metadata"] = {**(node.get("metadata") or {}), **metadata}
        for node_id in seed_ids:
            if node_id in nodes:
                nodes[node_id]["is_seed"] = True
                nodes[node_id]["seed_ids"] = [node_id]
                nodes[node_id]["role"] = "seed"
        values = list(edges.values())
        return {"seed": seed_ids[0], "seed_ids": list(seed_ids), "multi_seed": len(seed_ids) > 1,
            "seed_title": nodes.get(seed_ids[0], {}).get("title", ""), "nodes": list(nodes.values()), "edges": values,
                "stats": {"node_count": len(nodes), "citation_edge_count": sum(e["relation"] in ("CITES", "CITATION_SIMILAR_TO") for e in values), "similarity_edge_count": sum(e["relation"] == "EMBEDDING_SIMILAR_TO" for e in values)}}

    def _paper_discovery_citation_edges(papers: list[dict]) -> list[GraphEdge]:
        """Create directed CITES edges for references present in this graph."""
        paper_ids = {str(paper.get("id")) for paper in papers}
        edges: list[GraphEdge] = []
        seen: set[tuple[str, str]] = set()
        for paper in papers:
            source = str(paper.get("id"))
            metadata = paper.get("metadata") or {}
            discovered_from = str(metadata.get("discovered_from") or "")
            discovered_via = str(metadata.get("discovered_via") or "")
            if discovered_from in paper_ids and discovered_via == "references":
                pair = (discovered_from, source)
                if pair not in seen:
                    seen.add(pair)
                    edges.append(GraphEdge(discovered_from, source, "CITES", 1.0, {"direct": True, "discovered_via": "references"}))
            elif discovered_from in paper_ids and discovered_via == "citations":
                pair = (source, discovered_from)
                if pair not in seen:
                    seen.add(pair)
                    edges.append(GraphEdge(source, discovered_from, "CITES", 1.0, {"direct": True, "discovered_via": "citations"}))
            references = metadata.get("references", [])
            for target_value in references:
                target = str(target_value)
                if target == source or target not in paper_ids or (source, target) in seen:
                    continue
                seen.add((source, target))
                edges.append(GraphEdge(source, target, "CITES", 1.0, {"direct": True}))
        return edges

    def _normalize_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
        normalized: dict[tuple[str, str, str], GraphEdge] = {}
        for edge in edges:
            source = edge.target if edge.relation == "CITED_BY" else edge.source
            target = edge.source if edge.relation == "CITED_BY" else edge.target
            relation = "CITES" if edge.relation == "CITED_BY" else edge.relation
            key = (source, target, relation)
            metadata = {**(edge.metadata or {}), "direct": relation == "CITES" and edge.metadata.get("direct", True)}
            normalized[key] = GraphEdge(source, target, relation, edge.weight, metadata)
        return list(normalized.values())

    def _classify_roles(papers: list[dict], seed_ids: set[str], edges: list[GraphEdge]) -> dict[str, tuple[str, dict[str, object]]]:
        """Classify works from publication year and verified directed citations.

        Similarity, author and citation-similarity edges are deliberately not
        sufficient evidence for a prior/derivative label.
        """
        by_id = {str(paper.get("id")): paper for paper in papers}
        result: dict[str, tuple[str, dict[str, object]]] = {
            paper_id: ("seed", {"role_reason": "seed", "role_seed_ids": [paper_id]})
            for paper_id in seed_ids
            if paper_id in by_id
        }
        for paper_id, paper in by_id.items():
            if paper_id in result:
                continue
            year = paper.get("year")
            if not isinstance(year, int):
                result[paper_id] = ("related", {"role_reason": "missing_year"})
                continue
            evidence: list[dict[str, object]] = []
            for edge in edges:
                if edge.relation != "CITES" or (edge.metadata or {}).get("synthetic"):
                    continue
                if edge.target in seed_ids and edge.source == paper_id:
                    seed = by_id.get(edge.target)
                    if seed and isinstance(seed.get("year"), int) and year > seed["year"]:
                        evidence.append({"seed_id": edge.target, "direction": "cites_seed", "year": seed["year"]})
                elif edge.source in seed_ids and edge.target == paper_id:
                    seed = by_id.get(edge.source)
                    if seed and isinstance(seed.get("year"), int) and year < seed["year"]:
                        evidence.append({"seed_id": edge.source, "direction": "seed_cites", "year": seed["year"]})
            if evidence:
                direction = evidence[0]["direction"]
                role = "derivative" if direction == "cites_seed" else "prior"
                result[paper_id] = (role, {"role_reason": direction, "role_evidence": evidence})
            else:
                result[paper_id] = ("related", {"role_reason": "no_verified_directional_citation"})
        return result

    def _paper_identity(paper: dict) -> tuple[str, str]:
        metadata = paper.get("metadata") or {}
        external_ids = metadata.get("external_ids") or {}
        doi = str(metadata.get("doi") or external_ids.get("DOI") or "").lower().replace("https://doi.org/", "").strip()
        if doi:
            return "doi", doi
        paper_id = str(paper.get("id") or "")
        arxiv_id = external_ids.get("ArXiv") or external_ids.get("ARXIV")
        if arxiv_id or paper_id.lower().startswith("arxiv:"):
            return "arxiv", str(arxiv_id or paper_id.split(":", 1)[1]).lower().removesuffix("v1")
        title = re.sub(r"[^a-z0-9]+", " ", str(paper.get("title") or "").casefold()).strip()
        return "title", title

    def _merge_provider_papers(papers: list[dict]) -> list[dict]:
        """Merge provider records while retaining the richest metadata."""
        merged: dict[tuple[str, str], dict] = {}
        for paper in papers:
            key = _paper_identity(paper)
            if not key[1]:
                continue
            current = merged.get(key)
            if current is None:
                current = dict(paper)
                merged[key] = current
            else:
                for name, value in paper.items():
                    if name in {"id", "metadata"}:
                        continue
                    if current.get(name) in (None, "", [], {}) and value not in (None, "", [], {}):
                        current[name] = value
                old_metadata = current.get("metadata") or {}
                new_metadata = paper.get("metadata") or {}
                current["metadata"] = {**new_metadata, **old_metadata}
                methods = set(old_metadata.get("discovery_methods") or [])
                methods.update(new_metadata.get("discovery_methods") or [])
                for value in (old_metadata.get("discovered_via"), new_metadata.get("discovered_via")):
                    if value:
                        methods.add(str(value))
                if methods:
                    current["metadata"]["discovery_methods"] = sorted(methods)
                origins = set(old_metadata.get("discovered_froms") or [])
                origins.update(new_metadata.get("discovered_froms") or [])
                for value in (old_metadata.get("discovered_from"), new_metadata.get("discovered_from")):
                    if value:
                        origins.add(str(value))
                if origins:
                    current["metadata"]["discovered_froms"] = sorted(origins)
            metadata = current.setdefault("metadata", {})
            providers = set(metadata.get("providers") or [])
            provider = metadata.get("provider")
            if provider:
                providers.add(str(provider))
            paper_provider = (paper.get("metadata") or {}).get("provider")
            if paper_provider:
                providers.add(str(paper_provider))
            metadata["providers"] = sorted(providers)
        return list(merged.values())

    def _rank_candidates(papers: list[dict], seed_ids: set[str], minimum_year: int | None = None, year_weight: float = 0.0) -> list[dict]:
        """Rank candidates by composite evidence; citation is not required."""
        ranked: list[tuple[float, dict]] = []
        source_points = {
            "references": 35.0,
            "citations": 35.0,
            "semantic_recommendation": 15.0,
            "local_specter2": 20.0,
            "bibliographic_coupling": 12.0,
            "local_text": 6.0,
            "related": 3.0,
            "crossref_metadata": 2.0,
        }
        for paper in papers:
            if str(paper.get("id")) in seed_ids:
                continue
            metadata = paper.setdefault("metadata", {})
            method = str(metadata.get("discovered_via") or metadata.get("provider") or "related")
            methods = set(metadata.get("discovery_methods") or [])
            methods.add(method)
            score = sum(source_points.get(item, 1.0) for item in methods)
            embedding_score = float(metadata.get("embedding_score") or 0.0)
            shared_references = float(metadata.get("shared_reference_count") or 0.0)
            coupling_score = float(metadata.get("bibliographic_coupling_score") or 0.0)
            author_overlap = float(metadata.get("author_overlap") or 0.0)
            citation_count = float(paper.get("citation_count") or 0.0)
            explicit_citation = bool({"references", "citations"} & methods)
            # Citation direction is strong evidence, not an admission gate.
            score += 15.0 if explicit_citation else 0.0
            score += min(25.0, max(0.0, embedding_score) * 25.0)
            score += min(20.0, max(0.0, coupling_score) * 20.0)
            score += min(15.0, shared_references)
            score += min(5.0, max(0.0, author_overlap) * 5.0)
            score += min(10.0, citation_count / 100.0)
            metadata_complete = sum(bool(metadata.get(key) or paper.get(key))
                                    for key in ("doi", "arxiv_id", "openalex_id"))
            score += metadata_complete
            metadata["discovery_methods"] = sorted(methods)
            metadata["discovery_count"] = len(methods)
            metadata["selection_score"] = round(score, 6)
            if year_weight:
                year = paper.get("year")
                recency = 0.0 if not isinstance(year, int) else min(1.0, max(0.0, (year - (minimum_year or 2000)) / 20.0))
                metadata["year_score"] = round(recency, 6)
                metadata["year_weight"] = year_weight
                score += year_weight * recency * 100.0
                metadata["selection_score"] = round(score, 6)
            metadata["has_explicit_citation_evidence"] = explicit_citation
            ranked.append((score, paper))
        return [paper for _, paper in sorted(
            ranked,
            key=lambda item: (-item[0], -float((item[1].get("metadata") or {}).get("embedding_score") or 0),
                              -int(item[1].get("citation_count") or 0), str(item[1].get("title") or "")),
        )]

    def _select_top_candidates(candidates: list[dict], seed_ids: set[str], limit: int, minimum_year: int | None = None, year_weight: float = 0.0) -> list[dict]:
        """Apply final node budget after cross-provider merge and ranking.

        Seeds are protected first. Citation evidence receives a bounded reserve,
        then every remaining slot is filled by the composite score. A candidate
        without a citation can therefore be selected when its other evidence is
        strong enough.
        """
        if limit < 1:
            return []
        seeds = [paper for paper in candidates if str(paper.get("id")) in seed_ids]
        candidates = apply_year_policy(candidates, seed_ids, minimum_year, year_weight)
        ranked = _rank_candidates(candidates, seed_ids, minimum_year, year_weight)
        citation_candidates = [paper for paper in ranked
                       if (paper.get("metadata") or {}).get("has_explicit_citation_evidence")]
        citation_reserve = min(15, max(0, limit - len(seeds)))
        selected: list[dict] = []
        seen: set[str] = set()
        for paper in [*seeds, *citation_candidates[:citation_reserve], *ranked]:
            paper_id = str(paper.get("id"))
            if not paper_id or paper_id in seen:
                continue
            seen.add(paper_id)
            selected.append(paper)
            if len(selected) >= limit:
                break
        return selected

    def _expand_seed_from_sources(seed_id: str, limit: int, recommendation_seed_ids: list[str] | None = None) -> tuple[dict, list[dict]]:
        """Expand one seed from citation, semantic and local sources."""
        # Ask OpenAlex for a wider structural neighborhood; final selection is
        # performed after all providers are merged and ranked.
        source_limit = min(max(limit * 2, 20), 80)
        seed, openalex_candidates = open_academic.expand_openalex(seed_id, source_limit)
        records = [seed, *openalex_candidates]
        lookup_id = str((seed.get("metadata") or {}).get("doi") or "")
        if lookup_id:
            lookup_id = f"doi:{lookup_id}"
        elif str(seed_id).lower().startswith("arxiv:"):
            lookup_id = seed_id
        try:
            if lookup_id:
                scholar_seed, scholar_candidates = scholar.expand(lookup_id, min(limit, 20))
                records.extend([scholar_seed, *scholar_candidates])
            else:
                records.extend(scholar.search(seed.get("title", ""), min(limit, 20)))
        except Exception:
            pass
        try:
            positive_ids = []
            for positive_id in recommendation_seed_ids or [seed_id]:
                if str(positive_id).lower().startswith("openalex:"):
                    if str(positive_id) == seed_id and lookup_id:
                        positive_ids.append(lookup_id)
                    else:
                        try:
                            positive_work = open_academic.openalex_work(str(positive_id))
                            positive_doi = str((positive_work.get("metadata") or {}).get("doi") or "")
                            if positive_doi:
                                positive_ids.append(f"doi:{positive_doi}")
                        except Exception:
                            continue
                else:
                    positive_ids.append(str(positive_id))
            recommendations = scholar.recommendations(positive_ids, min(source_limit, 50))
            for paper in recommendations:
                paper.setdefault("metadata", {})["discovered_via"] = "semantic_recommendation"
                paper["metadata"]["discovered_from"] = seed["id"]
            records.extend(recommendations)
        except Exception:
            pass
        try:
            records.extend(open_academic.openalex_bibliographic_candidates(seed["id"], min(20, source_limit)))
        except Exception:
            pass
        try:
            for paper in service.search(seed.get("title", ""), min(limit, 20)):
                paper = dict(paper)
                paper["metadata"] = {**(paper.get("metadata") or {}),
                                     "discovered_via": "local_text", "discovered_from": seed["id"]}
                records.append(paper)
        except Exception:
            pass
        if local_semantic_search is not None:
            try:
                records.extend(local_semantic_search(seed, min(limit, 20)))
            except Exception:
                pass
        try:
            for paper in open_academic.crossref_search(seed.get("title", ""), min(10, limit)):
                paper.setdefault("metadata", {})["discovered_via"] = "crossref_metadata"
                paper["metadata"]["discovered_from"] = seed["id"]
                records.append(paper)
        except Exception:
            pass
        merged = _merge_provider_papers(records)
        selected_seed = next((paper for paper in merged if paper.get("id") == seed.get("id")), seed)
        seed_ids = {str(selected_seed.get("id"))}
        selected = _select_top_candidates(merged, seed_ids, limit)
        selected = [selected_seed] + [paper for paper in selected if str(paper.get("id")) != str(selected_seed.get("id"))]
        return selected_seed, selected[:limit]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        sample_path = Path(__file__).resolve().parents[2] / "docs/generated/integration-tests/first-full-graph/graph.json"
        return {
            "ok": True,
            "api_version": "0.2.0",
            "graph_sample": sample_path.exists(),
            "graph_sample_path": str(sample_path),
            "local_papers": len(service.store.papers),
            "local_edges": len(service.store.edges),
            "semantic_scholar_cached_requests": len(scholar._cache),
            "sources": ["local", "semantic_scholar"],
        }

    @app.get("/api/ready")
    def ready():
        """Readiness probe for the frontend-facing backend process."""
        sample_path = Path(__file__).resolve().parents[2] / "docs/generated/integration-tests/first-full-graph/graph.json"
        if not sample_path.exists():
            raise HTTPException(status_code=503, detail="graph sample is unavailable")
        return {"ready": True, "api_version": "0.2.0", "graph_sample": True}

    @app.get("/api/topic-graphs/{topic_id}")
    def topic_graph(topic_id: str):
        """Read a generated topic graph; this endpoint never calls providers."""
        if topic_store is None:
            raise HTTPException(status_code=404, detail="topic graph store is not configured")
        result = topic_store.graph(topic_id)
        if result is None:
            raise HTTPException(status_code=404, detail="topic graph not found")
        return result

    @app.get("/api/topic-forest")
    def topic_forest():
        """Return the local first-level/second-level topic forest and graph leaves."""
        if topic_store is None:
            raise HTTPException(status_code=404, detail="topic graph store is not configured")
        taxonomy = topic_store.taxonomy()
        summary_path = topic_store.root / "summary.json"
        summary = topic_store._read(summary_path) if summary_path.exists() else {}
        summary_by_topic = {
            str(item.get("topic_id")): item
            for item in summary.get("topics", [])
            if item.get("topic_id")
        }
        # The forest serves the completed OpenAlex-expanded graph variant.
        # Keep the taxonomy store unchanged, but switch graph leaves to the
        # year-2006 filtered build when it is available.
        incremental_root = topic_store.root.parent.parent / "openalex-seed-graphs-1000-2006-v4"
        graph_leaves: dict[str, list[dict[str, Any]]] = {}
        if incremental_root.exists():
            for path in sorted(incremental_root.glob("*/graph-*.json")):
                try:
                    graph = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                topic_id = str(graph.get("topic_id") or path.parent.name)
                nodes = graph.get("nodes") or []
                edges = graph.get("edges") or []
                # Generated topic graphs intentionally store a compact node
                # record. Enrich it from the local paper store when the
                # compact record has no abstract/authors/metadata.
                enriched_nodes = []
                for node in nodes:
                    node_id = str(node.get("id"))
                    local = service.store.paper(node_id)
                    if local is None and node_id.lower().startswith("arxiv:"):
                        local = service.store.paper(node_id.split(":", 1)[1])
                    if local is None:
                        enriched_nodes.append(node)
                        continue
                    enriched_nodes.append({
                        **local,
                        **node,
                        "authors": node.get("authors") or local.get("authors", []),
                        "abstract": node.get("abstract") or local.get("abstract", ""),
                        "keywords": node.get("keywords") or local.get("keywords", []),
                        "metadata": {**(local.get("metadata") or {}), **(node.get("metadata") or {})},
                    })
                if enriched_nodes:
                    graph = {**graph, "nodes": enriched_nodes}
                    nodes = enriched_nodes
                stats = graph.get("stats") or {}
                graph_leaves.setdefault(topic_id, []).append({
                    "graph_id": graph.get("graph_id") or path.stem,
                    "topic_id": topic_id,
                    "path": str(path.relative_to(incremental_root)),
                    "node_count": len(nodes),
                    "edge_count": len(edges),
                    "seed_count": len(graph.get("seed_ids") or []),
                    "expansion_count": graph.get("expansion_count", 0),
                    "error_count": len(graph.get("expansion_errors") or []),
                    "graph": graph,
                    "all_edge_endpoints_in_graph": stats.get("all_edge_endpoints_in_graph", True),
                })
        roots = []
        for first in taxonomy.get("first_levels", []):
            children = []
            for child in first.get("children", []):
                topic_id = str(child.get("id"))
                topic_summary = summary_by_topic.get(topic_id, {})
                leaves = graph_leaves.get(topic_id, [])
                children.append({
                    "id": topic_id,
                    "label": child.get("label", topic_id),
                    "keywords": child.get("keywords", []),
                    "candidate_count": topic_summary.get("candidate_count", 0),
                    "graph_count": len(leaves),
                    "node_count": sum(item["node_count"] for item in leaves),
                    "edge_count": sum(item["edge_count"] for item in leaves),
                    "graphs": leaves,
                })
            roots.append({"id": first.get("id"), "label": first.get("label"), "children": children})
        return {
            "schema_version": "topic_forest_v1",
            "root_count": len(roots),
            "leaf_count": sum(len(root["children"]) for root in roots),
            "graph_count": sum(len(child["graphs"]) for root in roots for child in root["children"]),
            "roots": roots,
        }

    @app.get("/api/arxiv-availability")
    def arxiv_availability(ids: str = Query(..., description="Comma-separated OpenAlex Work IDs")):
        """Look up arXiv associations for graph nodes through OpenAlex metadata."""
        work_ids = list(dict.fromkeys(value.strip() for value in ids.split(",") if value.strip()))[:40]
        result = []
        for work_id in work_ids:
            if not work_id.lower().startswith("openalex:"):
                continue
            try:
                if work_id not in arxiv_lookup_cache:
                    work = open_academic.openalex_work(work_id)
                    metadata = work.get("metadata") or {}
                    arxiv_lookup_cache[work_id] = {
                        "paper_id": work_id,
                        "arxiv_id": metadata.get("arxiv_id"),
                        "arxiv_url": metadata.get("arxiv_url"),
                        "arxiv_pdf_url": metadata.get("arxiv_pdf_url"),
                        "arxiv_location": bool(metadata.get("arxiv_location")),
                        "status": "linked" if metadata.get("arxiv_id") or metadata.get("arxiv_location") else "not_found",
                    }
            except Exception as error:
                arxiv_lookup_cache[work_id] = {"paper_id": work_id, "status": "lookup_failed", "error": str(error)}
            result.append(arxiv_lookup_cache[work_id])
        return {"results": result, "queried": len(work_ids)}

    @app.post("/api/topic-graphs/{topic_id}/seeds")
    def add_topic_seed(topic_id: str, payload: dict = Body(...)):
        """Compare a new seed with a topic graph and persist the chosen variant.

        A direct citation, shared author, or sufficiently strong embedding link
        extends the existing graph. Otherwise a new graph variant is created
        from the candidate seed. Provider expansion is explicit and limited.
        """
        if topic_store is None:
            raise HTTPException(status_code=404, detail="topic graph store is not configured")
        base = topic_store.graph(topic_id)
        if base is None:
            raise HTTPException(status_code=404, detail="topic graph not found")
        seed_id = str(payload.get("seed_id") or "").strip()
        if not seed_id:
            raise HTTPException(status_code=400, detail="seed_id required")
        # Compare against every persisted variant, not only the topic overview.
        # Existing variants are updated in place; no old graph is reconstructed
        # from only the new seed, so previously assigned papers cannot vanish.
        existing_variants = topic_store.variants(topic_id)
        if not existing_variants:
            existing_variants = [base]
        base_nodes = [dict(node) for variant in existing_variants for node in variant.get("nodes", [])]
        existing_ids = {str(node.get("id")) for node in base_nodes}
        candidate: dict | None = next((node for node in base_nodes if str(node.get("id")) == seed_id), None)
        discovered: list[dict] = []
        try:
            if candidate is None and seed_id.lower().startswith("openalex:"):
                candidate = open_academic.openalex_work(seed_id)
                for item in open_academic.openalex_search(candidate.get("title", ""), min(int(payload.get("expand_limit", 12)), 20)):
                    if item["id"] != candidate["id"]:
                        try:
                            discovered.append(open_academic.openalex_work(item["id"]))
                        except Exception:
                            continue
            elif candidate is None:
                candidate, discovered = scholar.expand(seed_id, min(int(payload.get("expand_limit", 12)), 20))
        except Exception as error:
            raise HTTPException(status_code=503, detail=f"seed provider expansion unavailable: {error}") from error
        if candidate is None:
            raise HTTPException(status_code=404, detail="seed paper not found")
        candidate = dict(candidate)
        candidate["id"] = str(candidate.get("id") or seed_id)
        candidate.setdefault("metadata", {})
        candidate["metadata"] = {**candidate["metadata"], "topic_id": topic_id, "seed_candidate": True}
        comparison_papers = [*base_nodes, candidate]
        _, comparison_edges = PaperGraphBuilder().build(comparison_papers, top_k=20, minimum_embedding_score=0.05)
        incident = [edge for edge in comparison_edges if candidate["id"] in {edge.source, edge.target}]
        direct = [edge for edge in incident if edge.relation in {"CITES", "CITED_BY"}]
        embedding = [edge for edge in incident if edge.relation == "EMBEDDING_SIMILAR_TO"]
        author = [edge for edge in incident if edge.relation == "AUTHOR_SHARED_BY"]
        max_embedding = max((edge.weight or 0.0 for edge in embedding), default=0.0)
        threshold = float(payload.get("embedding_threshold", 0.55))
        merge = bool(candidate["id"] in existing_ids or direct or author or max_embedding >= threshold)
        relation_basis = "existing_seed" if candidate["id"] in existing_ids else "citation" if direct else "author" if author else "embedding" if max_embedding >= threshold else "new_graph"
        if merge:
            graph_papers = [*comparison_papers, *discovered]
            target_variant = max(existing_variants, key=lambda variant: sum(
                1 for node in variant.get("nodes", []) if str(node.get("id")) in {edge.source for edge in incident} | {edge.target for edge in incident}
            ))
            target_ids = {str(node.get("id")) for node in target_variant.get("nodes", [])}
            graph_papers = [*target_variant.get("nodes", []), candidate, *discovered]
            seeds = [str(value) for value in target_variant.get("seed_ids", [target_variant.get("seed")]) if value]
            if candidate["id"] not in seeds:
                seeds.append(candidate["id"])
            graph = PaperGraphBuilder().response(graph_papers, seed=seeds[0], seeds=seeds, top_k=20, minimum_embedding_score=0.05)
            variant_id = str(target_variant.get("variant_id") or ("merged-" + "-".join(sorted(seeds))))
        else:
            graph_papers = [candidate, *discovered]
            graph = PaperGraphBuilder().response(graph_papers, seed=candidate["id"], seeds=[candidate["id"]], top_k=20, minimum_embedding_score=0.05)
            variant_id = "seed-" + candidate["id"].replace(":", "-")
        graph.update({"category": topic_id, "variant_id": variant_id, "decision": "merge" if merge else "new_graph",
                  "member_ids": sorted({str(node.get("id")) for node in graph.get("nodes", [])}),
                      "decision_basis": relation_basis, "comparison": {"direct_citation_count": len(direct), "shared_author_count": len(author), "max_embedding_score": max_embedding, "embedding_threshold": threshold},
                      "provider_expansion_count": len(discovered)})
        topic_store.save_variant(topic_id, variant_id, graph)
        return graph

    @app.get("/api/search")
    def search(q: str = Query(min_length=1), source_limit: int = Query(20, ge=1, le=100)):
        # Fetch a fixed candidate batch from every source, then rank all
        # candidates with one local scoring function. There is intentionally
        # no final 40-result cap; deduplication may still reduce the count.
        local = service.search(q, source_limit)
        external: list[dict] = []
        for search_provider in (scholar.search, open_academic.crossref_search, open_academic.openalex_search):
            try:
                external.extend(search_provider(q, source_limit))
            except Exception:
                continue
        candidates = local + external
        deduped: list[dict] = []
        seen_doi: set[str] = set()
        seen_titles: dict[str, tuple[dict, set[str]]] = {}
        for paper in candidates:
            metadata = paper.get("metadata") or {}
            doi = str(metadata.get("doi") or (metadata.get("external_ids") or {}).get("DOI") or "").lower()
            doi = re.sub(r"^https?://doi.org/", "", doi).strip()
            title = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(paper.get("title", "")).lower()).strip()
            authors = {re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(author).lower()).strip() for author in paper.get("authors", [])}
            existing = seen_titles.get(title)
            if doi and doi in seen_doi:
                continue
            if existing and (not authors or not existing[1] or existing[1] & authors):
                continue
            if doi:
                seen_doi.add(doi)
            if title:
                seen_titles[title] = (paper, authors)
            paper["relevance_score"] = PaperStore.score(q, paper)
            deduped.append(paper)
        deduped.sort(key=lambda paper: (-float(paper.get("relevance_score", 0)), str(paper.get("title", ""))))
        return {"results": deduped}

    @app.get("/api/search/crossref")
    def search_crossref(q: str = Query(min_length=1), limit: int = Query(40, ge=1, le=100)):
        try:
            return {"results": open_academic.crossref_search(q, limit), "provider": "crossref"}
        except Exception as error:
            raise HTTPException(status_code=503, detail="Crossref unavailable") from error

    @app.get("/api/search/openalex")
    def search_openalex(q: str = Query(min_length=1), limit: int = Query(40, ge=1, le=100)):
        try:
            return {"results": open_academic.openalex_search(q, limit), "provider": "openalex"}
        except Exception as error:
            raise HTTPException(status_code=503, detail="OpenAlex unavailable") from error

    @app.get("/api/discovery/search")
    def discovery_search(q: str = Query(min_length=2), limit: int = Query(40, ge=1, le=100)):
        return {"results": scholar.search(q, limit)}

    @app.get("/api/authors/search")
    def search_authors(q: str = Query(min_length=2), limit: int = Query(20, ge=1, le=100)):
        try:
            return {"results": scholar.search_authors(q, limit)}
        except Exception:
            return {"results": []}

    @app.get("/api/authors/{author_id:path}/papers")
    def author_papers(author_id: str, limit: int = Query(40, ge=1, le=100), offset: int = Query(0, ge=0)):
        try:
            return {"results": scholar.author_papers(author_id, limit, offset), "offset": offset, "limit": limit}
        except Exception as error:
            raise HTTPException(status_code=503, detail="author papers unavailable") from error

    @app.post("/api/discovery/more-like-this")
    def more_like_this(payload: dict = Body(...), limit: int = Query(40, ge=1, le=100)):
        merged = {}
        for paper_id in payload.get("paper_ids", [])[:10]:
            try:
                for paper in scholar.related(str(paper_id), max(5, limit // 2)):
                    merged[paper["id"]] = paper
            except Exception:
                continue
        return {"results": list(merged.values())[:limit]}

    @app.get("/api/graphs/realized-volatility")
    def realized_volatility_graph(limit: int = Query(40, ge=5, le=80)):
        """Return the bounded first full graph used by the web demonstration.

        The fixture contains provider-discovered papers and verified relation
        types. Selection is performed here so 20/40/80 always slice the same
        complete graph instead of creating different synthetic examples.
        """
        sample_path = Path(__file__).resolve().parents[2] / "docs/generated/integration-tests/first-full-graph/graph.json"
        if not sample_path.exists():
            raise HTTPException(status_code=503, detail="first full graph sample unavailable")
        try:
            sample = json.loads(sample_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=503, detail="first full graph sample unreadable") from error
        all_papers = [dict(paper) for paper in sample.get("nodes", [])]
        seed = next((paper for paper in all_papers if paper.get("id") == sample.get("seed")), all_papers[0])
        seed_id = str(seed["id"])
        all_edges = [GraphEdge(**edge) for edge in sample.get("edges", [])]
        ranked_papers: list[dict] = []
        for paper in all_papers:
            paper_id = str(paper.get("id"))
            metadata = paper.setdefault("metadata", {})
            direct_edges = [edge for edge in all_edges if edge.relation == "CITES" and paper_id in {edge.source, edge.target}]
            source_methods = set(metadata.get("discovery_methods") or [])
            discovered_via = metadata.get("discovered_via")
            if discovered_via:
                source_methods.add(str(discovered_via))
            score = (1000.0 if paper_id == seed_id else 0.0)
            score += 180.0 if direct_edges else 0.0
            score += min(90.0, float(paper.get("citation_count") or 0.0))
            score += min(40.0, 10.0 * len(source_methods))
            score += sum(float(edge.weight or 0.0) for edge in all_edges
                         if edge.relation in {"CITATION_SIMILAR_TO", "EMBEDDING_SIMILAR_TO"}
                         and paper_id in {edge.source, edge.target})
            metadata["selection_score"] = round(score, 6)
            metadata["discovery_methods"] = sorted(source_methods)
            metadata["has_explicit_citation_evidence"] = bool(direct_edges)
            ranked_papers.append(paper)
        ranked_papers.sort(key=lambda paper: (-float((paper.get("metadata") or {}).get("selection_score") or 0.0), str(paper.get("title") or "")))
        selected_ids = {seed_id}
        ranked_non_seed = [paper for paper in ranked_papers if str(paper.get("id")) != seed_id]
        selected_ids.update(str(paper.get("id")) for paper in ranked_non_seed[:max(0, limit - 1)])
        papers = [paper for paper in all_papers if str(paper.get("id")) in selected_ids]
        edges = [edge for edge in all_edges if edge.source in selected_ids and edge.target in selected_ids]
        role_info = _classify_roles(papers, {seed["id"]}, edges)
        nodes = [GraphNode(
            id=paper["id"], title=paper["title"], abstract=paper.get("abstract", ""),
            year=paper.get("year"), authors=paper.get("authors", []),
            citation_count=paper.get("citation_count", 0), global_impact=paper.get("global_impact", 0),
            is_seed=paper["id"] == seed["id"],
            role=role_info.get(paper["id"], ("related", {}))[0],
            metadata={**(paper.get("metadata") or {}), **role_info.get(paper["id"], ("related", {}))[1]},
        ) for paper in papers]
        response = GraphResponse(
            seed=seed["id"], seed_title=seed["title"], nodes=nodes, edges=edges,
            stats=GraphStats(len(nodes), len(edges), 0),
        ).to_dict()
        response["source"] = "first_full_graph"
        response["query"] = "first-full-graph sample"
        response["sample"] = True
        response["provenance"] = sample.get("provenance", {})
        return response

    @app.post("/api/graphs/seed-map")
    def seed_map(payload: dict = Body(...)):
        seed_ids = [str(value) for value in payload.get("seed_ids", []) if value][:8]
        minimum_year, year_weight = year_config(payload)
        if not seed_ids:
            raise HTTPException(status_code=400, detail="seed_ids required")
        if all(seed_id.lower().startswith("openalex:") for seed_id in seed_ids):
            from .verification import verified_reference_edges
            openalex_papers = []
            failed_openalex = []
            for seed_id in seed_ids:
                try:
                    seed, discovered = _expand_seed_from_sources(
                        seed_id, max(8, 40 // len(seed_ids)), recommendation_seed_ids=seed_ids
                    )
                    openalex_papers.extend([seed, *discovered])
                except Exception as error:
                    failed_openalex.append({"id": seed_id, "error": str(error)})
            if openalex_papers:
                openalex_papers = _merge_provider_papers(openalex_papers)
                seed_records = [paper for paper in openalex_papers if paper.get("id") in seed_ids]
                ranked_candidates = _select_top_candidates(openalex_papers, set(seed_ids), 40, minimum_year, year_weight)
                openalex_papers = seed_records + [paper for paper in ranked_candidates if paper.get("id") not in seed_ids]
                openalex_papers = openalex_papers[:40]
                verified_edges = verified_reference_edges(openalex_papers)
                role_info = _classify_roles(openalex_papers, set(seed_ids), verified_edges)
                nodes = [GraphNode(
                    id=paper["id"], title=paper["title"], abstract=paper.get("abstract", ""),
                    year=paper.get("year"), authors=paper.get("authors", []),
                    citation_count=paper.get("citation_count", 0), global_impact=paper.get("global_impact", 0),
                    is_seed=paper["id"] in seed_ids,
                    role=role_info.get(paper["id"], ("related", {}))[0],
                    metadata={**(paper.get("metadata") or {}), **role_info.get(paper["id"], ("related", {}))[1]},
                ) for paper in openalex_papers]
                response = GraphResponse(
                    seed=openalex_papers[0]["id"], seed_title=openalex_papers[0]["title"],
                    nodes=nodes, edges=verified_edges,
                    stats=GraphStats(len(nodes), len(verified_edges), 0),
                ).to_dict()
                response["seed_ids"] = list(seed_ids)
                response["multi_seed"] = len(openalex_papers) > 1
                response["source"] = "openalex"
                response["failed_seed_ids"] = failed_openalex
                response["filters"] = {"min_year": minimum_year, "year_weight": year_weight}
                return response
        graphs = []
        for seed_id in seed_ids:
            try:
                graphs.append(graph(seed_id))
            except Exception:
                try:
                    graphs.append(service.graph(seed_id, limit=40).to_dict())
                except KeyError:
                    continue
        if not graphs:
            raise HTTPException(status_code=404, detail="no seed found")
        return merge_graph_dicts(graphs, seed_ids)

    @app.post("/api/papers/parse-queue")
    def add_to_parse_queue(payload: dict = Body(...)):
        paper = payload.get("paper") if isinstance(payload.get("paper"), dict) else payload
        if not paper.get("id"):
            raise HTTPException(status_code=400, detail="paper id required")
        return queue_paper(paper, str(payload.get("reason") or "manual"))

    @app.get("/api/papers/parse-queue")
    def get_parse_queue():
        if not parse_queue_path.exists():
            return {"results": []}
        rows = []
        for line in parse_queue_path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return {"results": rows}

    @app.get("/api/maps")
    def get_maps():
        return {"results": list(maps.values())}

    @app.post("/api/maps")
    def create_map(payload: dict = Body(...)):
        import uuid
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        map_id = str(uuid.uuid4())
        item = {"id": map_id, "title": payload.get("title") or "Untitled research map", "seed_ids": payload.get("seed_ids", []), "graph": payload.get("graph", {}), "paper_ids": [node.get("id") for node in payload.get("graph", {}).get("nodes", [])], "created_at": now, "updated_at": now}
        maps[map_id] = item
        return item

    @app.delete("/api/maps/{map_id}")
    def remove_map(map_id: str):
        maps.pop(map_id, None)
        return {"ok": True}

    @app.post("/api/maps/{map_id}/copy")
    def duplicate_map(map_id: str):
        import copy, uuid
        if map_id not in maps:
            raise HTTPException(status_code=404, detail="map not found")
        item = copy.deepcopy(maps[map_id])
        item["id"] = str(uuid.uuid4())
        item["title"] = f'{item["title"]} (copy)'
        maps[item["id"]] = item
        return item

    @app.post("/api/maps/overlap")
    def maps_overlap(payload: dict = Body(...)):
        selected = [maps[map_id] for map_id in payload.get("map_ids", []) if map_id in maps]
        if len(selected) < 2:
            raise HTTPException(status_code=400, detail="at least two maps required")
        sets = [set(item.get("paper_ids", [])) for item in selected]
        common = set.intersection(*sets)
        union = set.union(*sets)
        all_nodes = {node["id"]: node for item in selected for node in item.get("graph", {}).get("nodes", [])}
        bridge = [all_nodes[node_id] for node_id in union if sum(node_id in values for values in sets) > 1 and node_id not in common]
        return {"intersection": [all_nodes[node_id] for node_id in common], "bridge_papers": bridge, "gaps": [f"{len(union - common)} papers are map-specific; investigate cross-topic links."]}

    @app.get("/api/graphs/{paper_id:path}")
    def graph(paper_id: str, expand_limit: int = Query(40, ge=5, le=80)):
        try:
            if paper_id.lower().startswith("openalex:"):
                from .verification import verified_reference_edges
                seed, discovered = _expand_seed_from_sources(paper_id, expand_limit)
                candidates = [seed, *discovered]
                edges = verified_reference_edges(candidates)
                role_info = _classify_roles(candidates, {seed["id"]}, edges)
                nodes = [GraphNode(
                    id=paper["id"], title=paper["title"], abstract=paper.get("abstract", ""),
                    year=paper.get("year"), authors=paper.get("authors", []),
                    citation_count=paper.get("citation_count", 0), global_impact=paper.get("global_impact", 0),
                    is_seed=paper["id"] == seed["id"],
                    role=role_info.get(paper["id"], ("related", {}))[0],
                    metadata={**(paper.get("metadata") or {}), **role_info.get(paper["id"], ("related", {}))[1]},
                ) for paper in candidates]
                response = GraphResponse(seed["id"], seed["title"], nodes, edges, GraphStats(len(nodes), len(edges), 0)).to_dict()
                response["source"] = "openalex"
                return response
            # Always prefer the live provider neighborhood when available.
            # The local graph is a fallback for IDs unavailable at Semantic
            # Scholar; otherwise it would stop at the small demo graph.
            seed, discovered = scholar.expand(paper_id, expand_limit)
            local_seed = service.store.paper(paper_id)
            if local_seed:
                seed = {**seed, **local_seed, "metadata": {**(seed.get("metadata") or {}), **(local_seed.get("metadata") or {})}, "id": paper_id}
                candidates = [seed, *discovered]
                unique = {paper["id"]: paper for paper in candidates}
                papers = list(unique.values())
                embeddings = HashEmbeddingEncoder().encode_papers(papers)
                embedding_edges = top_k_embedding_edges(embeddings, k=16, minimum_score=0.05)
                author_edges = top_k_author_edges({paper["id"]: paper for paper in papers}, k=8)
                references = {paper["id"]: set((paper.get("metadata") or {}).get("references", [])) for paper in papers}
                cited_by = {paper["id"]: set((paper.get("metadata") or {}).get("cited_by", [])) for paper in papers}
                citation_edges = [*provider_direct_citation_edges(references, {paper["id"] for paper in papers}), *top_k_citation_edges(references, cited_by, k=8, minimum_score=0.05)]
                direct_edges = _paper_discovery_citation_edges(papers)
                graph_edges = _normalize_edges([*direct_edges, *[GraphEdge(edge.source, edge.target, edge.relation, edge.weight, edge.metadata) for edge in [*citation_edges, *embedding_edges, *author_edges]]])
                role_info = _classify_roles(papers, {seed["id"]}, graph_edges)
                nodes = [GraphNode(id=paper["id"], title=paper["title"], abstract=paper.get("abstract", ""), year=paper.get("year"), authors=paper.get("authors", []), citation_count=paper.get("citation_count", 0), global_impact=paper.get("global_impact", 0), is_seed=paper["id"] == seed["id"], role=role_info.get(paper["id"], ("related", {}))[0], metadata={**(paper.get("metadata") or {}), **role_info.get(paper["id"], ("related", {}))[1]}) for paper in papers]
                return GraphResponse(seed["id"], seed["title"], nodes, graph_edges, GraphStats(len(nodes), len(direct_edges) + len(citation_edges), len(embedding_edges))).to_dict()
            candidates = [seed, *discovered]
            unique = {paper["id"]: paper for paper in candidates}
            papers = list(unique.values())
            embeddings = HashEmbeddingEncoder().encode_papers(papers)
            embedding_edges = top_k_embedding_edges(embeddings, k=16, minimum_score=0.05)
            author_edges = top_k_author_edges({paper["id"]: paper for paper in papers}, k=8)
            references = {paper["id"]: set((paper.get("metadata") or {}).get("references", [])) for paper in papers}
            cited_by = {paper["id"]: set((paper.get("metadata") or {}).get("cited_by", [])) for paper in papers}
            citation_edges = [*provider_direct_citation_edges(references, {paper["id"] for paper in papers}), *top_k_citation_edges(references, cited_by, k=8, minimum_score=0.05)]
            direct_edges = _paper_discovery_citation_edges(papers)
            graph_edges = _normalize_edges([*direct_edges, *[GraphEdge(edge.source, edge.target, edge.relation, edge.weight, edge.metadata) for edge in [*citation_edges, *embedding_edges, *author_edges]]])
            role_info = _classify_roles(papers, {seed["id"]}, graph_edges)
            nodes = [GraphNode(id=paper["id"], title=paper["title"], abstract=paper.get("abstract", ""), year=paper.get("year"), authors=paper.get("authors", []), citation_count=paper.get("citation_count", 0), global_impact=paper.get("global_impact", 0), is_seed=paper["id"] == seed["id"], role=role_info.get(paper["id"], ("related", {}))[0], metadata={**(paper.get("metadata") or {}), **role_info.get(paper["id"], ("related", {}))[1]}) for paper in papers]
            return GraphResponse(seed["id"], seed["title"], nodes, graph_edges, GraphStats(len(nodes), len(direct_edges) + len(citation_edges), len(embedding_edges))).to_dict()
        except Exception as discovery_error:
            try:
                # Keep local Digest graphs available, but do not silently
                # turn an external-paper failure into the eight-paper demo.
                local = service.store.paper(paper_id)
                if local is not None:
                    return service.graph(paper_id, expand_limit).to_dict()
            except KeyError:
                pass
            raise HTTPException(
                status_code=503,
                detail="Semantic Scholar expansion unavailable; retry shortly",
            ) from discovery_error

    @app.get("/api/papers/{paper_id:path}")
    def paper(paper_id: str):
        result = service.store.paper(paper_id)
        if result is None:
            raise HTTPException(status_code=404, detail="paper not found")
        return result

    return app