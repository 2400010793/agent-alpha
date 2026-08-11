#!/usr/bin/env python3
"""Build a bounded OpenAlex-backed pilot graph for one local digest topic.

The pilot keeps selected local digest papers as seed nodes, expands each seed
through OpenAlex references and cited-by works, and writes an auditable graph
without changing the existing offline topic graphs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from paper_graph.open_academic import OpenAcademicClient  # noqa: E402
from paper_graph.verification import verified_reference_edges  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def manifest_by_id(path: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for row in read_jsonl(path):
        value = str(row.get("paper_id") or row.get("arxiv_id") or "")
        value = value.removeprefix("arxiv:").split("v", 1)[0]
        if value:
            result[f"arxiv:{value}"] = row
    return result


def select_seeds(graph: dict[str, Any], manifest: dict[str, dict[str, Any]], count: int,
                 allowed_seed_ids: set[str] | None = None) -> list[dict[str, Any]]:
    candidates = []
    for node in graph.get("nodes", []):
        local_id = str(node.get("id"))
        if allowed_seed_ids is not None and local_id not in allowed_seed_ids:
            continue
        compact = manifest.get(local_id, {})
        openalex = compact.get("openalex") or {}
        if openalex.get("status") != "matched" or not openalex.get("openalex_id"):
            continue
        matches = [item for item in compact.get("topic_matches", [])
                   if item.get("topic_id") == graph.get("category")]
        if not matches:
            continue
        match = matches[0]
        score = int(match.get("score") or 0)
        candidates.append({
            "local_id": local_id,
            "title": node.get("title") or compact.get("title") or local_id,
            "openalex_id": f"openalex:{openalex['openalex_id']}",
            "openalex_score": float(openalex.get("score") or 0.0),
            "reference_count": int(openalex.get("reference_count") or 0),
            "topic_score": score,
            "title_match": bool(match.get("title_terms")),
            "selection_reason": "topic_match_and_openalex_identity",
        })
    candidates.sort(key=lambda item: (-int(item["title_match"]), -item["topic_score"], -item["reference_count"],
                                      -item["openalex_score"], item["local_id"]))
    return candidates[:count]


def select_incremental_seed_ids(graph: dict[str, Any], digest_queue: list[dict[str, Any]],
                                max_seeds: int = 5, minimum_priority: float = 0.75) -> list[str]:
    """Return new eligible local IDs without removing existing graph papers.

    A completed Digest result is required. ``digest_status`` is intentionally
    checked here, so merely downloading TeX or being highly ranked cannot turn
    a paper into a seed. Existing ``seed_ids`` are preserved and only the
    available slots are filled.
    """
    existing = [str(value) for value in graph.get("seed_ids", []) if value]
    if len(existing) >= max_seeds:
        return existing[:max_seeds]
    eligible = []
    for row in digest_queue:
        paper_id = str(row.get("paper_id") or row.get("arxiv_id") or "")
        if not paper_id or paper_id in existing:
            continue
        if row.get("digest_status") != "completed":
            continue
        priority = float((row.get("importance") or {}).get("digest_priority") or 0.0)
        if priority >= minimum_priority:
            eligible.append((priority, paper_id))
    eligible.sort(key=lambda item: (-item[0], item[1]))
    return existing + [paper_id for _, paper_id in eligible[:max_seeds - len(existing)]]


def cached_work(client: OpenAcademicClient, paper_id: str, cache: dict[str, Any], delay: float) -> dict[str, Any]:
    if paper_id in cache:
        return cache[paper_id]
    work = client.openalex_work(paper_id)
    cache[paper_id] = work
    if delay:
        time.sleep(delay)
    return work


def expand_seed(client: OpenAcademicClient, seed: dict[str, Any], cache: dict[str, Any], delay: float,
                per_direction: int) -> list[dict[str, Any]]:
    work = cached_work(client, seed["openalex_id"], cache, delay)
    work["id"] = seed["openalex_id"]
    work["metadata"] = {**(work.get("metadata") or {}), "local_id": seed["local_id"],
                         "source": "my-paper-digest-new2", "discovered_via": "seed",
                         "identity_match": "manifest_openalex_id"}
    records = [work]
    references = list((work.get("metadata") or {}).get("references") or [])[:per_direction]
    for reference_id in references:
        try:
            candidate = cached_work(client, reference_id, cache, delay)
        except Exception:
            continue
        candidate["metadata"] = {**(candidate.get("metadata") or {}),
                                  "discovered_from": seed["openalex_id"],
                                  "discovered_via": "references"}
        records.append(candidate)
    try:
        citing = client.openalex_citing_works(seed["openalex_id"], per_direction)
    except Exception:
        citing = []
    for candidate in citing:
        try:
            candidate = cached_work(client, candidate["id"], cache, delay)
        except Exception:
            continue
        candidate["metadata"] = {**(candidate.get("metadata") or {}),
                                  "discovered_from": seed["openalex_id"],
                                  "discovered_via": "citations"}
        records.append(candidate)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", default="limit_order_book")
    parser.add_argument("--graph-root", type=Path, default=ROOT / "docs/generated/digest-topic-graphs/three-ai-v1")
    parser.add_argument("--manifest", type=Path, default=ROOT / "docs/generated/parsed-paper-manifest/papers.jsonl")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/generated/external-pilot")
    parser.add_argument("--seed-count", type=int, default=5)
    parser.add_argument("--per-direction", type=int, default=8)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--max-nodes", type=int, default=40,
                        help="stop accepting expanded nodes once this graph size is reached")
    parser.add_argument("--seed-policy", type=Path, default=None,
                        help="JSON policy containing an explicit allowed_seed_ids list")
    args = parser.parse_args()
    if args.seed_count < 1 or args.seed_count > 5 or args.per_direction < 1:
        raise SystemExit("seed-count must be between 1 and 5; per-direction must be positive")
    if args.max_nodes < args.seed_count:
        raise SystemExit("max-nodes must be at least seed-count")

    graph = read_json(args.graph_root / "graphs" / f"topic_{args.topic}.json")
    manifest = manifest_by_id(args.manifest)
    allowed_seed_ids = None
    if args.seed_policy:
        policy = read_json(args.seed_policy)
        allowed_seed_ids = {str(value) for value in policy.get("allowed_seed_ids", [])}
        if not allowed_seed_ids:
            raise SystemExit("seed policy must contain a non-empty allowed_seed_ids list")
    seeds = select_seeds(graph, manifest, args.seed_count, allowed_seed_ids)
    if not seeds:
        raise SystemExit("no matched OpenAlex seeds found for topic")

    output = args.output_dir / args.topic
    output.mkdir(parents=True, exist_ok=True)
    (output / "seed_manifest.json").write_text(json.dumps(seeds, ensure_ascii=False, indent=2), encoding="utf-8")
    cache_path = output / "openalex_cache.json"
    cache = read_json(cache_path) if cache_path.exists() else {}
    client = OpenAcademicClient(timeout=20.0)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for seed in seeds:
        try:
            records.extend(expand_seed(client, seed, cache, args.delay, args.per_direction))
        except Exception as error:
            failures.append({"seed": seed["openalex_id"], "error": str(error)})
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    unique: dict[str, dict[str, Any]] = {}
    for paper in records:
        paper_id = str(paper.get("id") or "")
        if not paper_id:
            continue
        current = unique.get(paper_id)
        if current is None:
            unique[paper_id] = paper
            continue
        metadata = current.setdefault("metadata", {})
        incoming = paper.get("metadata") or {}
        methods = set(metadata.get("discovery_methods") or [])
        methods.update(incoming.get("discovery_methods") or [])
        for value in (metadata.get("discovered_via"), incoming.get("discovered_via")):
            if value:
                methods.add(str(value))
        if methods:
            metadata["discovery_methods"] = sorted(methods)
        origins = set(metadata.get("discovered_froms") or [])
        origins.update(incoming.get("discovered_froms") or [])
        for value in (metadata.get("discovered_from"), incoming.get("discovered_from")):
            if value:
                origins.add(str(value))
        if origins:
            metadata["discovered_froms"] = sorted(origins)

    seed_ids = {seed["openalex_id"] for seed in seeds}
    seed_records = [unique[seed_id] for seed_id in seed_ids if seed_id in unique]
    external = [paper for paper_id, paper in unique.items() if paper_id not in seed_ids]
    external.sort(key=lambda paper: (-int(paper.get("citation_count") or 0), str(paper.get("title") or "")))
    selected = seed_records + external[: max(0, args.max_nodes - len(seed_records))]
    local_ids = {str(seed["local_id"]) for seed in seeds}
    local_node_count = sum(1 for paper in selected if str((paper.get("metadata") or {}).get("local_id") or "") in local_ids)
    edges = verified_reference_edges(selected)
    graph_out = {"category": args.topic, "seed_ids": [seed["openalex_id"] for seed in seeds],
                 "multi_seed": len(seeds) > 1, "nodes": selected,
                 "edges": [{"source": edge.source, "target": edge.target, "relation": edge.relation,
                            "weight": edge.weight, "metadata": edge.metadata} for edge in edges],
                 "stats": {"node_count": len(selected), "verified_citation_edge_count": len(edges)},
                 "provenance": {"source": "openalex_pilot", "local_seed_count": local_node_count,
                                "external_node_count": len(selected) - local_node_count,
                                "max_nodes": args.max_nodes,
                                "expansion_stopped_at_limit": len(selected) >= args.max_nodes,
                                "new_digest_papers_are_seeds": False}}
    (output / "graph.json").write_text(json.dumps(graph_out, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"topic": args.topic, "seed_count": len(seeds), "final_node_count": len(selected),
              "local_node_count": local_node_count, "external_node_count": len(selected) - local_node_count,
              "verified_citation_edge_count": len(edges), "cache_size": len(cache),
              "failed_seed_count": len(failures), "failures": failures}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
