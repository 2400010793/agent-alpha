#!/usr/bin/env python3
"""Build exactly one bounded multi-provider graph and stop.

This is a smoke test, not a full topic run. It uses one verified seed, records
all provider outcomes, writes the first graph, and exits immediately.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_graph.embeddings import HashEmbeddingEncoder, LocalSemanticIndex, Specter2Encoder
from paper_graph.graph_builder import PaperGraphBuilder
from paper_graph.open_academic import OpenAcademicClient
from paper_graph.semantic_scholar import SemanticScholarClient


def record(log: Path, step: str, status: str, **data: Any) -> None:
    event = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "step": step, "status": status, **data}
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(json.dumps(event, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", default="arxiv:1608.01795")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/generated/integration-tests/first-full-graph")
    parser.add_argument("--openalex-cache", type=Path,
                        default=ROOT / "docs/generated/external-pilot/limit_order_book/openalex_cache.json")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    log = args.output / "graph_test_log.jsonl"
    log.write_text("", encoding="utf-8")

    def call(step: str, fn):
        started = time.monotonic()
        try:
            value = fn()
            record(log, step, "ok", elapsed_seconds=round(time.monotonic() - started, 3),
                   result_size=len(value) if hasattr(value, "__len__") else None)
            return value
        except Exception as error:
            record(log, step, "error", elapsed_seconds=round(time.monotonic() - started, 3),
                   error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
            return []

    openalex = OpenAcademicClient(timeout=12)
    scholar = SemanticScholarClient(timeout=12)
    seed_cache = json.loads(args.openalex_cache.read_text(encoding="utf-8"))
    manifest_rows = [json.loads(line) for line in (ROOT / "docs/generated/parsed-paper-manifest/papers.jsonl").read_text(encoding="utf-8").splitlines() if line]
    manifest = next(row for row in manifest_rows if row.get("paper_id") == args.seed)
    openalex_id = f"openalex:{manifest['openalex']['openalex_id']}"
    seed_oa = seed_cache.get(openalex_id)
    if not seed_oa:
        record(log, "openalex_seed_cache", "error", error="verified cache entry missing", cache_key=openalex_id)
        return 1
    record(log, "openalex_seed_cache", "ok", cache_key=openalex_id, source="verified_local_cache")

    seed = {"id": args.seed, "title": seed_oa.get("title", manifest.get("title", "")),
            "authors": seed_oa.get("authors", []), "year": seed_oa.get("year"),
            "abstract": seed_oa.get("abstract", ""), "url": manifest.get("url", ""),
            "metadata": {"provider": "openalex", "openalex_id": openalex_id,
                         "doi": seed_oa.get("metadata", {}).get("doi"),
                         "verified_relations": True, "identity_status": "unique_openalex"}}

    papers: list[dict[str, Any]] = [seed]
    try:
        citations = call("semantic_scholar_citations", lambda: scholar._list_relation(args.seed, "citations", args.limit))
        for paper in citations:
            paper.setdefault("metadata", {}).update({"discovered_from": args.seed, "discovered_via": "citations"})
        papers.extend(citations)
        references = call("semantic_scholar_references", lambda: scholar._list_relation(args.seed, "references", args.limit))
        for paper in references:
            paper.setdefault("metadata", {}).update({"discovered_from": args.seed, "discovered_via": "references"})
        papers.extend(references)
        recommendations = call("semantic_scholar_recommendations", lambda: scholar.recommendations([args.seed], args.limit))
        for paper in recommendations:
            paper.setdefault("metadata", {}).update({"discovered_from": args.seed, "discovered_via": "semantic_recommendation"})
        papers.extend(recommendations)
    except Exception as error:
        record(log, "semantic_scholar", "error", error_type=type(error).__name__, error=str(error))

    crossref = call("crossref_search", lambda: openalex.crossref_search(seed["title"], args.limit))
    for paper in crossref:
        paper.setdefault("metadata", {}).update({"discovered_from": args.seed, "discovered_via": "crossref_metadata"})
    papers.extend(crossref)

    coupling = call("openalex_bibliographic_coupling", lambda: openalex.openalex_bibliographic_candidates(openalex_id, args.limit))
    for paper in coupling:
        paper.setdefault("metadata", {}).update({"discovered_from": args.seed, "discovered_via": "bibliographic_coupling"})
    papers.extend(coupling)

    # Add a small verified OpenAlex reference neighborhood from the existing
    # cache. These are explicit citation candidates, not recommendations.
    refs = seed_oa.get("metadata", {}).get("references", [])[:args.limit]
    for ref_id in refs:
        ref = seed_cache.get(ref_id)
        if ref:
            item = dict(ref)
            item["metadata"] = {**(item.get("metadata") or {}), "discovered_from": openalex_id,
                                 "discovered_via": "references", "provider": "openalex"}
            papers.append(item)
    record(log, "openalex_reference_cache", "ok", requested=len(refs), returned=sum(1 for ref_id in refs if ref_id in seed_cache))

    # Try SPECTER2 once in strict offline mode. Do not wait for network retries.
    old_offline = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        specter_encoder = Specter2Encoder()
        local_index = LocalSemanticIndex([seed], encoder=specter_encoder, threshold=0.0)
        specter_results = local_index.search(seed, limit=args.limit)
        record(log, "local_specter2", "ok", result_size=len(specter_results), model=specter_encoder.model_name)
        embedding_encoder = specter_encoder
    except Exception as error:
        record(log, "local_specter2", "error", error_type=type(error).__name__,
               error=str(error), traceback=traceback.format_exc())
        record(log, "local_specter2_fallback", "ok", reason=type(error).__name__,
               message=str(error), fallback="HashEmbedding")
        embedding_encoder = HashEmbeddingEncoder()
    finally:
        if old_offline is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = old_offline

    # De-duplicate by stable provider/local ID while preserving first discovery.
    unique: dict[str, dict[str, Any]] = {}
    for paper in papers:
        paper_id = str(paper.get("id") or "")
        if paper_id and paper_id not in unique:
            unique[paper_id] = paper
    builder = PaperGraphBuilder(encoder=embedding_encoder)
    graph = builder.response(list(unique.values()), seed=args.seed, seeds=[args.seed], top_k=20,
                             minimum_embedding_score=0.05)
    graph.update({"category": "limit_order_book", "variant_id": "first-full-graph",
                  "identity_scope": "one_unique_openalex_seed",
                  "provenance": {"openalex_verified_seed": True, "provider_sources": [
                      "semantic_scholar_citations", "semantic_scholar_recommendations",
                      "crossref", "openalex_bibliographic_coupling", "openalex_references_cache"],
                      "embedding_model": type(embedding_encoder).__name__}})
    graph_path = args.output / "graph.json"
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    record(log, "first_graph_written", "ok", path=str(graph_path), node_count=len(graph["nodes"]),
           edge_count=len(graph["edges"]), citation_edges=sum(edge["relation"] == "CITES" for edge in graph["edges"]))
    summary = {"stopped_after_first_graph": True, "seed": args.seed, "node_count": len(graph["nodes"]),
               "edge_count": len(graph["edges"]), "log": str(log), "graph": str(graph_path)}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
