#!/usr/bin/env python3
"""Build topic-local graph variants by processing parsed papers one at a time.

For every secondary topic, each already-parsed local paper is considered in
priority order. It is assigned to the best existing graph when related, or it
starts a new graph otherwise. A graph has at most five seeds. Adding a seed
preserves all existing nodes and performs one bounded OpenAlex expansion for
that graph. This command writes a new output root and never rewrites the
frozen topic graphs.
"""
from __future__ import annotations

import argparse
import json
import re
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from paper_graph.embeddings import HashEmbeddingEncoder
from paper_graph.graph_builder import PaperGraphBuilder
from paper_graph.open_academic import OpenAcademicClient
from paper_graph.semantic_scholar import SemanticScholarClient

MAX_SEEDS = 5
DEFAULT_PER_DIRECTION = 8


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def canonical(value: Any) -> str:
    return re.sub(r"^arxiv:", "", str(value or "").strip(), flags=re.I).split("v", 1)[0]


def local_id(value: Any) -> str:
    text = str(value or "")
    return text if text.lower().startswith("arxiv:") else f"arxiv:{canonical(text)}"


def topic_score(row: dict[str, Any], topic_id: str) -> float:
    return max((float(item.get("score") or 0) for item in row.get("topic_matches", [])
                if item.get("topic_id") == topic_id), default=0.0)


def priority(row: dict[str, Any]) -> float:
    return float((row.get("importance") or {}).get("digest_priority") or 0.0)


def has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def has_paper_id(row: dict[str, Any]) -> bool:
    return has_value(row.get("paper_id") or row.get("arxiv_id"))


def is_completed_parse(row: dict[str, Any]) -> bool:
    """Return whether a local row contains all three completed AI stages.

    The compact parsed-paper manifest is generated only from rows satisfying
    this contract, but checking the stage fields as well keeps this script safe
    when a broader manifest is supplied explicitly.
    """
    stage_keys = (
        ("llm_reading_note", "reading_note", "reading_note_v1"),
        ("paper_hf_factors", "article_opinions", "opinion_analysis"),
        ("llm_faithfulness_audit", "faithfulness_audit", "llm_opinion_faithfulness_audit"),
    )
    # Compact manifests intentionally omit the large stage payloads. Their
    # presence in the parsed-paper-manifest directory is the completion marker.
    if not any(has_value(row.get(key)) for keys in stage_keys for key in keys):
        # Existing compact manifests were produced by
        # prepare_parsed_topic_manifest.py from completed three-stage rows
        # before the explicit marker was added.
        return bool(row.get("parsed_manifest_complete") or "topic_matches" in row)
    return all(any(has_value(row.get(key)) for key in keys) for keys in stage_keys)


def is_seed_candidate(queue_row: dict[str, Any], manifest_row: dict[str, Any] | None,
                      *, strict_openalex: bool = True) -> bool:
    """Only completed local papers with an ID may become initial/added seeds."""
    if not manifest_row:
        return False
    openalex = manifest_row.get("openalex") or {}
    has_openalex = openalex.get("status") == "matched" and has_value(openalex.get("openalex_id"))
    return bool(manifest_row and has_paper_id(queue_row) and has_paper_id(manifest_row)
                and is_completed_parse(manifest_row)
                and (has_openalex if strict_openalex else True))


def node_from_manifest(row: dict[str, Any]) -> dict[str, Any]:
    paper_id = local_id(row.get("paper_id") or row.get("arxiv_id"))
    openalex = row.get("openalex") or {}
    metadata = {"source": "my-paper-digest-new2", "local_id": paper_id,
                "openalex_id": openalex.get("openalex_id"),
                "identity_status": openalex.get("status")}
    return {"id": paper_id, "title": row.get("title") or paper_id, "year": openalex.get("year"),
            "authors": row.get("authors") or [], "abstract": row.get("abstract") or "",
            "url": row.get("url"), "role": "seed", "is_seed": True, "metadata": metadata}


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """Write one graph checkpoint atomically after every state transition."""
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def load_graph_checkpoints(topic_dir: Path) -> list[dict[str, Any]]:
    graphs = []
    for path in sorted(topic_dir.glob("graph-*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("graph_id"):
            graphs.append(value)
    return graphs


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def year_score(candidate: dict[str, Any], minimum_year: int) -> float:
    year = candidate.get("year")
    if not isinstance(year, int):
        return 0.0
    return min(1.0, max(0.0, (year - minimum_year) / max(1, datetime.now().year - minimum_year)))


def candidate_rank(candidate: dict[str, Any], *, minimum_year: int = 2006, year_weight: float = 0.0) -> tuple[float, int, int, str]:
    """Rank provider candidates while preserving their relation provenance."""
    metadata = candidate.get("metadata") or {}
    discovered_via = str(metadata.get("discovered_via") or "")
    source_rank = {
        "references": 5,
        "citations": 4,
        "semantic_scholar": 3,
        "related": 2,
        "local_parsed_manifest": 1,
    }.get(discovered_via, 0)
    return (source_rank + year_weight * year_score(candidate, minimum_year),
            int(candidate.get("citation_count") or 0),
            int(metadata.get("reference_count") or 0), str(candidate.get("id") or ""))


def merge_candidates(graph: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add provider candidates once and preserve repeated discovery methods."""
    existing = {str(node.get("id")): node for node in graph.get("nodes", []) if node.get("id")}
    added: list[dict[str, Any]] = []
    for raw_candidate in candidates:
        candidate_id = str(raw_candidate.get("id") or "")
        if not candidate_id:
            continue
        if candidate_id in existing:
            current_metadata = existing[candidate_id].setdefault("metadata", {})
            incoming_metadata = raw_candidate.get("metadata") or {}
            methods = set(current_metadata.get("discovery_methods") or [])
            for value in (current_metadata.get("discovered_via"), incoming_metadata.get("discovered_via")):
                if value:
                    methods.add(str(value))
            if methods:
                current_metadata["discovery_methods"] = sorted(methods)
            continue
        candidate = dict(raw_candidate)
        candidate.setdefault("role", "related")
        candidate.setdefault("is_seed", False)
        graph.setdefault("nodes", []).append(candidate)
        existing[candidate_id] = candidate
        added.append(candidate)
    return added


def apply_year_policy(candidates: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    """Keep only candidates inside the configured publication-year window."""
    kept = []
    for candidate in candidates:
        year = candidate.get("year")
        if not isinstance(year, int) or year < args.min_year:
            continue
        metadata = candidate.setdefault("metadata", {})
        score = year_score(candidate, args.min_year)
        metadata["year_score"] = round(score, 6)
        metadata["year_weight"] = args.year_weight
        metadata["min_publication_year"] = args.min_year
        metadata["selection_score"] = round(args.year_weight * score, 6)
        kept.append(candidate)
    return kept


def expand_graph_seed(graph: dict[str, Any], seed: dict[str, Any], *,
                      client: OpenAcademicClient, scholar: SemanticScholarClient,
                      cache: dict[str, dict[str, Any]], local_candidates: list[dict[str, Any]],
                      args: argparse.Namespace) -> list[dict[str, Any]]:
    """Expand one seed once and record all provider errors."""
    seed_id = str(seed.get("id") or "")
    expanded_ids = {str(value) for value in graph.get("expanded_seed_ids", [])}
    if not seed_id or seed_id in expanded_ids:
        return []
    candidates, errors = expand_seed(client, scholar, seed, cache, local_candidates,
                                     args.per_direction, args.delay)
    candidates = apply_year_policy(candidates, args)
    graph.setdefault("expansion_errors", []).extend(errors)
    graph.setdefault("expanded_seed_ids", []).append(seed_id)
    graph["expansion_count"] = int(graph.get("expansion_count", 0)) + 1
    return merge_candidates(graph, candidates)


def promote_external_seeds(graph: dict[str, Any], candidates: list[dict[str, Any]], *,
                            client: OpenAcademicClient, scholar: SemanticScholarClient,
                            cache: dict[str, dict[str, Any]], local_candidates: list[dict[str, Any]],
                            args: argparse.Namespace) -> None:
    """Promote provider candidates to the remaining seed slots and expand once."""
    pending = list(candidates)
    while pending and len(graph.get("seed_ids", [])) < args.max_seeds:
        seed_ids = {str(value) for value in graph.get("seed_ids", [])}
        options = [
            item for item in pending
            if str(item.get("id") or "") not in seed_ids
            and str((item.get("metadata") or {}).get("provider") or "")
            in {"openalex", "semantic_scholar", "crossref"}
        ]
        options = apply_year_policy(options, args)
        if not options:
            return
        candidate = sorted(
            options,
            key=lambda item: candidate_rank(item, minimum_year=args.min_year, year_weight=args.year_weight),
            reverse=True,
        )[0]
        candidate_id = str(candidate.get("id") or "")
        pending = [item for item in pending if str(item.get("id") or "") != candidate_id]
        if not candidate_id:
            continue
        node = next((item for item in graph["nodes"] if str(item.get("id")) == candidate_id), None)
        if node is None:
            added = merge_candidates(graph, [candidate])
            if not added:
                continue
            node = added[0]
        node["is_seed"] = True
        node["role"] = "seed"
        node["seed_ids"] = [candidate_id]
        graph["seed_ids"].append(candidate_id)
        pending.extend(expand_graph_seed(graph, node, client=client, scholar=scholar,
                                         cache=cache, local_candidates=local_candidates, args=args))


def finalize_graph(graph: dict[str, Any], args: argparse.Namespace) -> None:
    """Normalize one checkpoint while preserving all required seed nodes."""
    graph["seed_ids"] = list(dict.fromkeys(str(value) for value in graph.get("seed_ids", []) if value))[:args.max_seeds]
    seed_ids = set(graph["seed_ids"])
    unique_nodes: dict[str, dict[str, Any]] = {}
    for node in graph.get("nodes", []):
        node_id = str(node.get("id") or "")
        if node_id and node_id not in unique_nodes:
            unique_nodes[node_id] = node
    seed_nodes = [unique_nodes[node_id] for node_id in graph["seed_ids"] if node_id in unique_nodes]
    other_nodes = sorted(
        (node for node_id, node in unique_nodes.items() if node_id not in seed_ids),
        key=lambda node: candidate_rank(node, minimum_year=args.min_year, year_weight=args.year_weight),
        reverse=True,
    )
    graph["nodes"] = (seed_nodes + other_nodes)[:args.max_nodes]
    graph["seed_ids"] = [node_id for node_id in graph["seed_ids"] if node_id in {str(node.get("id")) for node in graph["nodes"]}]
    if graph["nodes"] and graph["seed_ids"]:
        node_ids = {str(node.get("id")) for node in graph["nodes"]}
        # Provider records can contain references to works that were not
        # selected into this bounded graph. Build relations from a sanitized
        # view so no edge can point outside the persisted node set.
        build_nodes = []
        for node in graph["nodes"]:
            safe_node = dict(node)
            metadata = dict(safe_node.get("metadata") or {})
            metadata["references"] = [str(value) for value in metadata.get("references", [])
                                       if str(value) in node_ids]
            if str(metadata.get("discovered_from") or "") not in node_ids:
                metadata.pop("discovered_from", None)
                metadata.pop("discovered_via", None)
            safe_node["metadata"] = metadata
            build_nodes.append(safe_node)
        _, edges = PaperGraphBuilder(encoder=HashEmbeddingEncoder()).build(
            build_nodes, top_k=20, minimum_embedding_score=0.05)
        normalized_edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        for edge in edges:
            if edge.source not in node_ids or edge.target not in node_ids or edge.source == edge.target:
                continue
            if edge.relation in {"CITATION_SIMILAR_TO", "EMBEDDING_SIMILAR_TO", "AUTHOR_SHARED_BY"}:
                endpoints = tuple(sorted((edge.source, edge.target)))
            else:
                endpoints = (edge.source, edge.target)
            key = (*endpoints, edge.relation)
            normalized_edges[key] = {"source": edge.source, "target": edge.target,
                                     "relation": edge.relation, "weight": edge.weight,
                                     "metadata": edge.metadata}
        graph["edges"] = list(normalized_edges.values())
    else:
        graph["edges"] = []
    # Annotate directional citation roles for the local graph UI. A work
    # cited by a seed is prior work; a later work citing a seed is derivative.
    node_by_id = {str(node.get("id")): node for node in graph["nodes"]}
    for node in graph["nodes"]:
        node_id = str(node.get("id"))
        if node_id in seed_ids:
            node["role"] = "seed"
            node["is_seed"] = True
            continue
        evidence = []
        node_year = node.get("year")
        for edge in graph["edges"]:
            if edge.get("relation") != "CITES":
                continue
            source = str(edge.get("source"))
            target = str(edge.get("target"))
            if source == node_id and target in seed_ids:
                seed_year = node_by_id.get(target, {}).get("year")
                if isinstance(node_year, int) and isinstance(seed_year, int) and node_year > seed_year:
                    evidence.append({"role": "derivative", "seed_id": target, "direction": "cites_seed"})
            elif target == node_id and source in seed_ids:
                seed_year = node_by_id.get(source, {}).get("year")
                if isinstance(node_year, int) and isinstance(seed_year, int) and node_year < seed_year:
                    evidence.append({"role": "prior", "seed_id": source, "direction": "seed_cites"})
        if evidence:
            node["role"] = evidence[0]["role"]
            metadata = node.setdefault("metadata", {})
            metadata["role_reason"] = evidence[0]["direction"]
            metadata["role_evidence"] = evidence
    edge_counts = {}
    for edge in graph["edges"]:
        relation = str(edge.get("relation") or "unknown")
        edge_counts[relation] = edge_counts.get(relation, 0) + 1
    node_count = len(graph["nodes"])
    max_edge_count = (node_count * (node_count - 1)
                      + 3 * node_count * (node_count - 1) // 2)
    if len(graph["edges"]) > max_edge_count:
        raise RuntimeError(
            f"edge invariant violated for {graph.get('graph_id')}: "
            f"{len(graph['edges'])} edges for {node_count} nodes; "
            f"maximum is {max_edge_count}"
        )
    graph["stats"] = {"node_count": len(graph["nodes"]), "edge_count": len(graph["edges"]),
                      "edge_counts_by_relation": edge_counts,
                      "seed_count": len(graph["seed_ids"]), "expansion_count": graph.get("expansion_count", 0),
                      "max_seeds": args.max_seeds, "max_nodes": args.max_nodes,
                      "max_allowed_edge_count": max_edge_count,
                      "all_edge_endpoints_in_graph": all(
                          edge.get("source") in {str(node.get("id")) for node in graph["nodes"]}
                          and edge.get("target") in {str(node.get("id")) for node in graph["nodes"]}
                          for edge in graph["edges"]
                      )}
    graph["provenance"] = {"source": "incremental_topic_graphs", "network_expansion": not args.no_network,
                           "min_publication_year": args.min_year, "year_weight": args.year_weight,
                           "strict_openalex_seed_candidates": args.strict_openalex,
                           "parsed_papers_are_seed_candidates": True,
                           "external_nodes_can_be_seeds": True,
                           "external_seed_expansion_depth": 1}


def citation_related(candidate: dict[str, Any], nodes: list[dict[str, Any]]) -> bool:
    candidate_id = str(candidate.get("id"))
    for node in nodes:
        refs = {(str(value)) for value in (node.get("metadata") or {}).get("references", [])}
        if candidate_id in refs or str(node.get("id")) in set((candidate.get("metadata") or {}).get("references", [])):
            return True
    return False


def compare(candidate: dict[str, Any], nodes: list[dict[str, Any]], threshold: float) -> tuple[bool, float, str]:
    if str(candidate.get("id")) in {str(node.get("id")) for node in nodes}:
        return True, 1.0, "same_paper"
    if citation_related(candidate, nodes):
        return True, 1.0, "explicit_citation"
    _, edges = PaperGraphBuilder(encoder=HashEmbeddingEncoder()).build(
        [*nodes, candidate], top_k=max(8, len(nodes)), minimum_embedding_score=0.05)
    incident = [edge for edge in edges if str(candidate.get("id")) in {edge.source, edge.target}]
    score = max((float(edge.weight or 0.0) for edge in incident
                 if edge.relation == "EMBEDDING_SIMILAR_TO"), default=0.0)
    return score >= threshold, score, "embedding" if score >= threshold else "new_graph"


def expand_seed(openalex: OpenAcademicClient, scholar: SemanticScholarClient,
                seed: dict[str, Any], cache: dict[str, dict[str, Any]],
                local_candidates: list[dict[str, Any]], per_direction: int,
                delay: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    openalex_id = str((seed.get("metadata") or {}).get("openalex_id") or "")
    if openalex_id:
        provider_id = openalex_id if openalex_id.startswith("openalex:") else f"openalex:{openalex_id}"
        try:
            if provider_id not in cache:
                cache[provider_id] = openalex.openalex_work(provider_id)
                if delay:
                    time.sleep(delay)
            work = cache[provider_id]
            references = list((work.get("metadata") or {}).get("references") or [])[:per_direction]
            for reference_id in references:
                if reference_id not in cache:
                    try:
                        cache[reference_id] = openalex.openalex_work(reference_id)
                    except Exception as error:
                        errors.append({"source": "openalex_references", "id": reference_id,
                                       "error": str(error), "error_type": type(error).__name__, "retryable": True})
                        continue
                    if delay:
                        time.sleep(delay)
                item = dict(cache[reference_id])
                item.setdefault("metadata", {})["discovered_via"] = "references"
                item["metadata"]["discovered_from"] = provider_id
                candidates.append(item)
            try:
                citing = openalex.openalex_citing_works(provider_id, per_direction)
            except Exception as error:
                citing = []
                errors.append({"source": "openalex_citations", "id": provider_id,
                               "error": str(error), "error_type": type(error).__name__, "retryable": True})
            for item in citing:
                item_id = str(item.get("id") or "")
                if not item_id:
                    continue
                if item_id not in cache:
                    try:
                        cache[item_id] = openalex.openalex_work(item_id)
                    except Exception as error:
                        errors.append({"source": "openalex_citations", "id": item_id,
                                       "error": str(error), "error_type": type(error).__name__, "retryable": True})
                        continue
                    if delay:
                        time.sleep(delay)
                full = dict(cache[item_id])
                full.setdefault("metadata", {})["discovered_via"] = "citations"
                full["metadata"]["discovered_from"] = provider_id
                candidates.append(full)
        except Exception as error:
            errors.append({"source": "openalex", "id": provider_id,
                           "error": str(error), "error_type": type(error).__name__, "retryable": True})

    scholar_id = seed.get("id") or ""
    try:
        _, scholar_candidates = scholar.expand(str(scholar_id), per_direction)
        for item in scholar_candidates:
            item.setdefault("metadata", {})["discovered_via"] = item["metadata"].get("discovered_via", "semantic_scholar")
            item["metadata"]["discovered_from"] = str(scholar_id)
        candidates.extend(scholar_candidates)
    except Exception as error:
        errors.append({"source": "semantic_scholar", "id": str(scholar_id),
                       "error": str(error), "error_type": type(error).__name__, "retryable": True})

    seed_id = str(seed.get("id"))
    local_ids = {str(item.get("id")) for item in local_candidates}
    for item in local_candidates:
        item_id = str(item.get("id"))
        if not item_id or item_id == seed_id or item_id not in local_ids:
            continue
        local = dict(item)
        local["role"] = "related"
        local["is_seed"] = False
        local["metadata"] = {**(local.get("metadata") or {}), "discovered_via": "local_parsed_manifest",
                              "discovered_from": seed_id, "external_seed_candidate": False}
        candidates.append(local)
    if delay:
        time.sleep(delay)
    return candidates, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-root", type=Path, default=Path("docs/generated/digest-topic-graphs/three-ai-v2"))
    parser.add_argument("--queue", type=Path, default=None,
                        help="deduplicated parsed-paper queue; defaults to the graph queue")
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--topic", default=None)
    parser.add_argument("--max-seeds", type=int, default=MAX_SEEDS)
    parser.add_argument("--max-nodes", type=int, default=40)
    parser.add_argument("--per-direction", type=int, default=DEFAULT_PER_DIRECTION)
    parser.add_argument("--embedding-threshold", type=float, default=0.55)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--no-network", action="store_true", help="assign papers without OpenAlex expansion")
    parser.add_argument("--strict-openalex", action=argparse.BooleanOptionalAction, default=True,
                        help="only use parsed local papers with a matched OpenAlex ID (default: true)")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True,
                        help="resume from graph checkpoints and decision logs (default: true)")
    parser.add_argument("--min-year", type=int, default=2006,
                        help="exclude discovered and seed-candidate papers before this year")
    parser.add_argument("--year-weight", type=float, default=0.2,
                        help="bounded recency bonus used when ordering provider candidates")
    args = parser.parse_args()
    if not 1 <= args.max_seeds <= MAX_SEEDS:
        raise SystemExit("max-seeds must be between 1 and 5")
    if args.max_nodes < 1:
        raise SystemExit("max-nodes must be positive")
    if args.min_year < 1900 or args.year_weight < 0:
        raise SystemExit("min-year must be plausible and year-weight must be non-negative")
    queue_path = args.queue or args.graph_root / "digest_graph_queue.jsonl"
    output_root = args.output_root or args.graph_root / "incremental-topic-graphs-v1"
    queue = {str(row.get("paper_id")): row for row in read_jsonl(queue_path) if row.get("paper_id")}
    manifest_path = args.manifest or args.graph_root.parents[2] / "parsed-paper-manifest" / "papers.jsonl"
    manifest = {local_id(row.get("paper_id") or row.get("arxiv_id")): row
                for row in read_jsonl(manifest_path)
                if has_paper_id(row)}
    topics = sorted({topic for row in queue.values() for topic in row.get("topic_ids", [])})
    if args.topic:
        topics = [args.topic]
    client = OpenAcademicClient(timeout=20.0)
    scholar = SemanticScholarClient(timeout=20.0)
    cache: dict[str, dict[str, Any]] = {}
    summary: list[dict[str, Any]] = []
    for topic_id in topics:
        candidates = [row for row in queue.values()
                      if topic_id in row.get("topic_ids", [])
                      and is_seed_candidate(
                          row,
                          manifest.get(local_id(row.get("paper_id") or row.get("arxiv_id"))),
                          strict_openalex=args.strict_openalex)]
        candidates.sort(key=lambda row: (-topic_score(manifest.get(local_id(row.get("paper_id")), {}), topic_id),
                        -priority(row), str(row.get("paper_id"))))
        local_candidates = [
            node_from_manifest(manifest[local_id(row.get("paper_id") or row.get("arxiv_id"))])
            for row in candidates
        ]
        topic_dir = output_root / topic_id
        topic_dir.mkdir(parents=True, exist_ok=True)
        decision_path = topic_dir / "decisions.jsonl"
        graphs = load_graph_checkpoints(topic_dir) if args.resume else []
        completed_ids = set()
        if args.resume and decision_path.exists():
            for row in read_jsonl(decision_path):
                if row.get("paper_id"):
                    completed_ids.add(str(row["paper_id"]))
        graphs_by_id = {str(graph["graph_id"]): graph for graph in graphs}
        decisions: list[dict[str, Any]] = []
        for row in candidates:
            candidate = node_from_manifest(manifest[local_id(row.get("paper_id") or row.get("arxiv_id"))])
            if candidate["id"] in completed_ids:
                continue
            matches = []
            for graph in graphs:
                related, score, basis = compare(candidate, graph["nodes"], args.embedding_threshold)
                if related:
                    matches.append((score, graph, basis))
            matches.sort(key=lambda item: (-item[0], item[1]["graph_id"]))
            if matches:
                _, graph, basis = matches[0]
                can_seed = len(graph["seed_ids"]) < args.max_seeds
                if candidate["id"] not in {str(node.get("id")) for node in graph["nodes"]}:
                    candidate["is_seed"] = can_seed
                    candidate["role"] = "seed" if can_seed else "related"
                    graph["nodes"].append(candidate)
                if can_seed and candidate["id"] not in graph["seed_ids"]:
                    graph["seed_ids"].append(candidate["id"])
                    candidate["seed_ids"] = [candidate["id"]]
                    if not args.no_network:
                        expand_graph_seed(graph, candidate, client=client, scholar=scholar,
                                          cache=cache, local_candidates=local_candidates, args=args)
                        promote_external_seeds(
                            graph,
                            list(graph.get("nodes", [])),
                            client=client,
                            scholar=scholar,
                            cache=cache,
                            local_candidates=local_candidates,
                            args=args,
                        )
                decision = {"topic_id": topic_id, "paper_id": candidate["id"], "decision": "merge",
                            "graph_id": graph["graph_id"], "basis": basis, "became_seed": can_seed}
                decisions.append(decision)
                finalize_graph(graph, args)
                atomic_write_json(topic_dir / f"{graph['graph_id']}.json", graph)
                append_jsonl(decision_path, decision)
                completed_ids.add(candidate["id"])
                continue
            graph_id = f"graph-{len(graphs) + 1:03d}"
            graph = {"topic_id": topic_id, "graph_id": graph_id, "seed_ids": [candidate["id"]],
                     "nodes": [candidate], "expansion_errors": [], "expansion_count": 0,
                     "expanded_seed_ids": []}
            if not args.no_network:
                discovered = expand_graph_seed(
                    graph, candidate, client=client, scholar=scholar, cache=cache,
                    local_candidates=local_candidates, args=args,
                )
                promote_external_seeds(
                    graph,
                    discovered,
                    client=client,
                    scholar=scholar,
                    cache=cache,
                    local_candidates=local_candidates,
                    args=args,
                )
            graphs.append(graph)
            graphs_by_id[graph_id] = graph
            decision = {"topic_id": topic_id, "paper_id": candidate["id"], "decision": "new_graph",
                        "graph_id": graph_id, "basis": "no_matching_graph", "became_seed": True}
            decisions.append(decision)
            finalize_graph(graph, args)
            atomic_write_json(topic_dir / f"{graph_id}.json", graph)
            append_jsonl(decision_path, decision)
            completed_ids.add(candidate["id"])
        for graph in graphs:
            finalize_graph(graph, args)
            atomic_write_json(topic_dir / f"{graph['graph_id']}.json", graph)
        summary.append({"topic_id": topic_id, "graph_count": len(graphs), "candidate_count": len(candidates),
                        "seed_count": sum(len(graph["seed_ids"]) for graph in graphs),
                        "node_count": sum(len(graph["nodes"]) for graph in graphs)})
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(json.dumps({"topics": summary, "max_seeds": args.max_seeds,
                                                            "max_nodes": args.max_nodes,
                                                            "network_expansion": not args.no_network,
                                                            "source_graphs_modified": False, "min_publication_year": args.min_year,
                                                            "year_weight": args.year_weight}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"topic_count": len(summary), "output_root": str(output_root), "source_graphs_modified": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
