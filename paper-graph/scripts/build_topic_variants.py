#!/usr/bin/env python3
"""Build deterministic local multi-seed variants from a frozen topic graph set.

This stage is deliberately offline. It decides merge/new-variant using explicit
citation evidence first, then embedding similarity, and finally shared authors
combined with embedding similarity. OpenAlex expansion is a later, bounded stage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from paper_graph.embeddings import HashEmbeddingEncoder, Specter2Encoder  # noqa: E402
from paper_graph.graph_builder import PaperGraphBuilder  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def variant_id(seed_ids: list[str]) -> str:
    digest = hashlib.sha1("|".join(sorted(seed_ids)).encode("utf-8")).hexdigest()[:12]
    return f"variant-{digest}"


def authors(node: dict[str, Any]) -> set[str]:
    return {str(value).casefold().strip() for value in node.get("authors", []) if value}


def explicit_citation(candidate: str, existing: set[str], nodes: list[dict[str, Any]]) -> bool:
    for node in nodes:
        if str(node.get("id")) not in existing:
            continue
        references = (node.get("metadata") or {}).get("references", [])
        if candidate in {str(value) for value in references}:
            return True
    return False


def relation_basis(candidate: dict[str, Any], existing_nodes: list[dict[str, Any]], threshold: float,
                   encoder: Any) -> tuple[bool, str, float]:
    candidate_id = str(candidate["id"])
    existing_ids = {str(node["id"]) for node in existing_nodes}
    if candidate_id in existing_ids:
        return True, "same_paper", 1.0
    if explicit_citation(candidate_id, existing_ids, [*existing_nodes, candidate]):
        return True, "explicit_citation", 1.0
    _, edges = PaperGraphBuilder(encoder=encoder).build([*existing_nodes, candidate], top_k=max(8, len(existing_nodes)))
    incident = [edge for edge in edges if candidate_id in {edge.source, edge.target}]
    embedding = max((float(edge.weight or 0.0) for edge in incident if edge.relation == "EMBEDDING_SIMILAR_TO"), default=0.0)
    has_author = any(edge.relation == "AUTHOR_SHARED_BY" for edge in incident)
    if embedding >= threshold:
        return True, "embedding", embedding
    if has_author and embedding >= threshold * 0.8:
        return True, "shared_author_and_embedding", embedding
    return False, "new_variant", embedding


def build_variant(topic_id: str, nodes: list[dict[str, Any]], core_seed_ids: list[str], output_root: Path,
                  encoder: Any) -> dict[str, Any]:
    builder = PaperGraphBuilder(encoder=encoder)
    graph = builder.response(nodes, seed=core_seed_ids[0], seeds=core_seed_ids, top_k=20, minimum_embedding_score=0.05)
    graph.update({"category": topic_id, "variant_id": variant_id(core_seed_ids), "seed_ids": sorted(core_seed_ids),
                  "core_seed_ids": sorted(core_seed_ids),
                  "member_ids": sorted(str(node["id"]) for node in nodes),
                  "provenance": {"stage": "offline_multi_seed", "external_expansion": False}})
    path = output_root / "variants" / topic_id / f"{graph['variant_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"topic_id": topic_id, "variant_id": graph["variant_id"], "seed_ids": sorted(core_seed_ids),
            "core_seed_ids": sorted(core_seed_ids), "member_ids": graph["member_ids"],
            "node_count": len(graph.get("nodes", [])), "edge_count": len(graph.get("edges", [])),
            "external_node_count": 0, "decision_basis": "initial_seed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-root", type=Path, default=ROOT / "docs/generated/digest-topic-graphs/three-ai-v2")
    parser.add_argument("--topic", help="只处理一个二级主题，例如 limit_order_book")
    parser.add_argument("--embedding-threshold", type=float, default=0.55)
    parser.add_argument("--embedding", choices=("hash", "specter2"), default="hash")
    args = parser.parse_args()
    encoder = Specter2Encoder() if args.embedding == "specter2" else HashEmbeddingEncoder()
    graph_root = args.graph_root
    graph_dir = graph_root / "graphs"
    index: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for graph_path in sorted(graph_dir.glob("topic_*.json")):
        topic_id = graph_path.stem.removeprefix("topic_")
        if args.topic and topic_id != args.topic:
            continue
        base = read_json(graph_path)
        topic_nodes = [dict(node) for node in base.get("nodes", [])]
        variants: list[dict[str, Any]] = []
        for position, candidate in enumerate(topic_nodes, start=1):
            selected: dict[str, Any] | None = None
            selected_basis = "new_variant"
            selected_score = 0.0
            for item in variants:
                merge, basis, score = relation_basis(candidate, item["nodes"], args.embedding_threshold, encoder)
                if merge and (selected is None or score > selected_score):
                    selected, selected_basis, selected_score = item, basis, score
            if selected is None:
                item = {"nodes": [candidate], "seed_ids": [str(candidate["id"])]}
                variants.append(item)
                decisions.append({"topic_id": topic_id, "position": position, "candidate_id": candidate["id"], "decision": "new_graph", "basis": "initial_seed", "variant_seed_ids": [str(candidate["id"])]})
            else:
                selected["nodes"].append(candidate)
                selected.setdefault("member_ids", []).append(str(candidate["id"]))
                decisions.append({"topic_id": topic_id, "position": position, "candidate_id": candidate["id"], "decision": "merge", "basis": selected_basis, "score": round(selected_score, 6), "variant_seed_ids": sorted(selected["seed_ids"])})
        for item in variants:
            index.append(build_variant(topic_id, item["nodes"], item["seed_ids"], graph_root, encoder))
    (graph_root / "variant_index.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in index), encoding="utf-8")
    (graph_root / "variant_decisions.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in decisions), encoding="utf-8")
    print(json.dumps({"topics": len({row['topic_id'] for row in index}), "variants": len(index), "decisions": len(decisions), "external_expansion": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
