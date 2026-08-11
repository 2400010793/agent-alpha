#!/usr/bin/env python3
"""Select a balanced ~1,000-paper seed pool and build 5-seed topic graphs.

The selection stage balances topic memberships (targeting about 20 papers per
one of 54 topics), deduplicates globally by OpenAlex ID, and ranks ties by
identity completeness, citation count, and recency. The graph stage keeps the
selected papers as the only Seeds: OpenAlex-expanded papers are always related
nodes and never promoted to Seeds.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from paper_graph.graph_builder import PaperGraphBuilder
from paper_graph.open_academic import OpenAcademicClient


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def rank(row: dict[str, Any], year: int = 2016) -> tuple[float, int, int, str]:
    identity = 1 if row.get("doi") else 0
    paper_year = row.get("year") if isinstance(row.get("year"), int) else year
    recency = max(0.0, min(1.0, (paper_year - year) / max(1, 2026 - year)))
    citations = math.log1p(max(0, int(row.get("citation_count") or 0)))
    return (identity + 0.35 * recency + 0.12 * citations, int(row.get("citation_count") or 0), paper_year, str(row.get("openalex_id")))

def external_rank(item: dict[str, Any], minimum_year: int, year_weight: float) -> tuple[float, int, int, str]:
    """Rank filtered OpenAlex nodes while preserving relation provenance."""
    metadata = item.get("metadata") or {}
    year = item.get("year") if isinstance(item.get("year"), int) else minimum_year
    recency = max(0.0, min(1.0, (year - minimum_year) / max(1, datetime.now().year - minimum_year)))
    relation_bonus = {"references": 2.0, "citations": 1.5}.get(str(metadata.get("discovered_via")), 0.0)
    return (relation_bonus + year_weight * recency,
            int(item.get("citation_count") or 0), year, str(item.get("id") or ""))


def select_balanced(rows: list[dict[str, Any]], target: int, per_topic: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("openalex_id") and row.get("identity_value"):
            current = by_id.get(str(row["openalex_id"]))
            if current is None or rank(row) > rank(current):
                by_id[str(row["openalex_id"])] = dict(row)
    for row in by_id.values():
        row["topic_ids"] = sorted(set(str(x) for x in row.get("topic_ids", [])))
    topics = sorted({topic for row in by_id.values() for topic in row["topic_ids"]})
    selected: dict[str, dict[str, Any]] = {}
    topic_selected: dict[str, list[str]] = {topic: [] for topic in topics}
    # Greedily maximize under-covered topic quotas. This preserves balance
    # after global truncation and rewards one paper covering several deficits.
    while len(selected) < target:
        counts = {topic: len(ids) for topic, ids in topic_selected.items()}
        options = [row for row in by_id.values() if str(row["openalex_id"]) not in selected]
        if not options:
            break
        deficient = [topic for topic, count in counts.items() if count < per_topic]
        if not deficient:
            break
        def coverage_score(row: dict[str, Any]) -> tuple[float, float, int, int, str]:
            covered = [topic for topic in row["topic_ids"] if topic in deficient]
            deficit_gain = sum(per_topic - counts[topic] for topic in covered)
            return (float(deficit_gain), rank(row)[0], rank(row)[1], rank(row)[2], str(row["openalex_id"]))
        row = max(options, key=coverage_score)
        paper_id = str(row["openalex_id"])
        selected[paper_id] = row
        for topic in row["topic_ids"]:
            if topic in topic_selected and len(topic_selected[topic]) < per_topic:
                topic_selected[topic].append(paper_id)
    remaining = sorted((row for row in by_id.values() if row["openalex_id"] not in selected), key=rank, reverse=True)
    for row in remaining:
        if len(selected) >= target:
            break
        selected[str(row["openalex_id"])] = row
    result = sorted(selected.values(), key=lambda row: (-rank(row)[0], str(row["openalex_id"])))[:target]
    selected_ids = {str(row["openalex_id"]) for row in result}
    topic_counts = {topic: sum(topic in row.get("topic_ids", []) for row in result) for topic in topics}
    summary = {"input_rows": len(rows), "unique_input_papers": len(by_id), "selected_papers": len(result),
               "topic_count": len(topics), "target_per_topic": per_topic,
               "topic_memberships": sum(topic_counts.values()), "topic_counts": topic_counts,
               "topics_below_target": sorted(topic for topic, count in topic_counts.items() if count < per_topic),
               "selected_ids": len(selected_ids)}
    return result, summary


def openalex_node(item: dict[str, Any], *, role: str = "related", source: str = "openalex") -> dict[str, Any]:
    metadata = dict(item.get("metadata") or {})
    metadata["provider"] = source
    metadata["source_role"] = role
    return {"id": str(item.get("id")), "title": item.get("title") or "Untitled paper",
            "authors": item.get("authors") or [], "year": item.get("year"),
            "citation_count": int(item.get("citation_count") or 0), "url": item.get("url") or "",
            "abstract": item.get("abstract") or "", "keywords": item.get("keywords") or [],
            "role": role, "is_seed": role == "seed", "metadata": metadata}


def candidate_node(row: dict[str, Any]) -> dict[str, Any]:
    openalex_id = str(row["openalex_id"])
    return openalex_node({"id": openalex_id, "title": row.get("title"), "authors": row.get("authors"),
                          "year": row.get("year"), "citation_count": row.get("citation_count"),
                          "url": row.get("url"), "metadata": {"provider": "openalex",
                          "openalex_id": openalex_id, "doi": row.get("doi"),
                          "arxiv_id": row.get("arxiv_id"), "identity_type": row.get("identity_type"),
                          "identity_value": row.get("identity_value"), "source": "selected_seed_pool"}}, role="seed")


def expand_seed(client: OpenAcademicClient, seed: dict[str, Any], cache: dict[str, dict[str, Any]], per_direction: int, delay: float) -> list[dict[str, Any]]:
    seed_id = str(seed["id"])
    if seed_id not in cache:
        cache[seed_id] = client.openalex_work(seed_id)
        if delay:
            time.sleep(delay)
    work = cache[seed_id]
    candidates: list[dict[str, Any]] = []
    references = list((work.get("metadata") or {}).get("references") or [])[:per_direction]
    for reference_id in references:
        if reference_id not in cache:
            try:
                cache[reference_id] = client.openalex_work(reference_id)
            except Exception:
                continue
            if delay:
                time.sleep(delay)
        item = dict(cache[reference_id])
        item.setdefault("metadata", {}).update({"discovered_via": "references", "discovered_from": seed_id})
        candidates.append(item)
    try:
        citing = client.openalex_citing_works(seed_id, per_direction)
    except Exception:
        citing = []
    for item in citing:
        item.setdefault("metadata", {}).update({"discovered_via": "citations", "discovered_from": seed_id})
        candidates.append(item)
    return candidates


def build_graphs(selected: list[dict[str, Any]], output: Path, max_seeds: int, max_nodes: int,
                 per_direction: int, delay: float, network: bool, topic_filter: str | None,
                 min_year: int, year_weight: float) -> dict[str, Any]:
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for row in selected:
        for topic in row.get("topic_ids", []):
            by_topic.setdefault(str(topic), []).append(row)
    if topic_filter:
        by_topic = {topic_filter: by_topic.get(topic_filter, [])}
    client = OpenAcademicClient(timeout=20.0)
    cache_path = output / "openalex-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    builder = PaperGraphBuilder()
    summaries = []
    for topic, topic_rows in sorted(by_topic.items()):
        topic_rows = sorted(topic_rows, key=rank, reverse=True)
        topic_dir = output / topic
        topic_dir.mkdir(parents=True, exist_ok=True)
        graphs = []
        for offset in range(0, len(topic_rows), max_seeds):
            seed_rows = topic_rows[offset:offset + max_seeds]
            if not seed_rows:
                continue
            nodes = [candidate_node(row) for row in seed_rows]
            seed_ids = [node["id"] for node in nodes]
            if network:
                external: dict[str, dict[str, Any]] = {}
                for seed in list(nodes):
                    try:
                        for item in expand_seed(client, seed, cache, per_direction, delay):
                            item_id = str(item.get("id") or "")
                            item_year = item.get("year")
                            if (item_id and item_id not in {str(node["id"]) for node in nodes}
                                    and isinstance(item_year, int) and item_year >= min_year):
                                existing = external.get(item_id)
                                if existing is None or external_rank(item, min_year, year_weight) > external_rank(existing, min_year, year_weight):
                                    external[item_id] = item
                    except Exception as error:
                        seed.setdefault("metadata", {}).setdefault("expansion_errors", []).append(str(error))
                ranked_external = sorted(external.values(),
                                         key=lambda item: external_rank(item, min_year, year_weight),
                                         reverse=True)
                nodes.extend(openalex_node(item) for item in ranked_external[:max(0, max_nodes - len(nodes))])
            nodes = nodes[:max_nodes]
            records, edges = builder.build(nodes, top_k=20, minimum_embedding_score=0.05)
            graph = {"schema_version": "paper_graph_openalex_seed_v1", "graph_id": f"graph-{offset // max_seeds + 1:03d}",
                     "topic_id": topic, "seed_ids": seed_ids, "nodes": records,
                     "edges": [{"source": edge.source, "target": edge.target, "relation": edge.relation,
                                "weight": edge.weight, "metadata": edge.metadata} for edge in edges],
                     "stats": {"seed_count": len(seed_ids), "node_count": len(records), "edge_count": len(edges),
                               "network_expansion": network, "max_seeds": max_seeds, "max_nodes": max_nodes},
                     "provenance": {"source": "selected_seed_pool", "external_nodes_never_seeds": True,
                                    "per_direction": per_direction, "min_publication_year": min_year,
                                    "year_weight": year_weight, "external_nodes_year_filtered": network}}
            graph_path = topic_dir / f"{graph['graph_id']}.json"
            write_json(graph_path, graph)
            graphs.append(graph)
        summaries.append({"topic_id": topic, "seed_count": sum(len(g["seed_ids"]) for g in graphs),
                          "graph_count": len(graphs), "node_count": sum(len(g["nodes"]) for g in graphs),
                          "edge_count": sum(len(g["edges"]) for g in graphs)})
        write_json(cache_path, cache)
        print(json.dumps(summaries[-1], ensure_ascii=False), flush=True)
    summary = {"schema_version": "paper_graph_openalex_seed_v1", "selected_count": len(selected),
               "topic_count": len(summaries), "max_seeds": max_seeds, "max_nodes": max_nodes,
               "network_expansion": network, "topics": summaries}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("docs/generated/topic-seed-candidates-2016-v1.jsonl"))
    parser.add_argument("--selected", type=Path, default=Path("docs/generated/selected-seeds-1000-2016-v1.jsonl"))
    parser.add_argument("--selection-summary", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("docs/generated/openalex-seed-graphs-1000-2016-v1"))
    parser.add_argument("--target", type=int, default=1000)
    parser.add_argument("--per-topic", type=int, default=20)
    parser.add_argument("--max-seeds", type=int, default=5)
    parser.add_argument("--max-nodes", type=int, default=40)
    parser.add_argument("--per-direction", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--topic", default=None)
    parser.add_argument("--network", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-year", type=int, default=2016)
    parser.add_argument("--year-weight", type=float, default=0.35)
    args = parser.parse_args()
    if args.target < 1 or args.per_topic < 1 or not 1 <= args.max_seeds <= 5 or args.max_nodes < args.max_seeds:
        raise SystemExit("invalid target, per-topic, max-seeds, or max-nodes")
    if args.min_year < 1900 or args.year_weight < 0:
        raise SystemExit("min-year must be plausible and year-weight must be non-negative")
    selected, selection_summary = select_balanced(read_jsonl(args.input), args.target, args.per_topic)
    write_jsonl(args.selected, selected)
    summary_path = args.selection_summary or args.selected.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(selection_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(selection_summary, ensure_ascii=False), flush=True)
    build_summary = build_graphs(selected, args.output, args.max_seeds, args.max_nodes,
                                 args.per_direction, args.delay, args.network, args.topic,
                                 args.min_year, args.year_weight)
    print(json.dumps({"selection": selection_summary, "build": build_summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
