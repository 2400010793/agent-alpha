#!/usr/bin/env python3
"""Project verified claim-level relations into one bounded paper graph."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from paper_graph.claim_relations import ClaimRelationV1, project_verified_relations
from paper_graph.graph import validate_edges
from paper_graph.models import PaperEdge


def read_relations(path: Path) -> list[ClaimRelationV1]:
    relations: list[ClaimRelationV1] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            relations.append(ClaimRelationV1.from_mapping(value))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid claim relation at line {line_number}: {exc}") from exc
    return relations


def enrich_graph(graph: dict[str, Any], relations: list[ClaimRelationV1]) -> dict[str, Any]:
    node_ids = {str(node.get("id")) for node in graph.get("nodes", []) if node.get("id")}
    projected = project_verified_relations(relations, node_ids)
    errors = validate_edges(projected)
    if errors:
        raise ValueError("invalid projected claim relations: " + "; ".join(errors))

    result = dict(graph)
    existing = [dict(edge) for edge in graph.get("edges", [])]
    existing_relation_ids = {
        str((edge.get("metadata") or {}).get("relation_id"))
        for edge in existing
        if (edge.get("metadata") or {}).get("relation_id")
    }
    added = []
    for edge in projected:
        relation_id = str(edge.metadata["relation_id"])
        if relation_id in existing_relation_ids:
            continue
        added.append({
            "source": edge.source,
            "target": edge.target,
            "relation": edge.relation,
            "weight": edge.weight,
            "metadata": edge.metadata,
        })
        existing_relation_ids.add(relation_id)
    result["edges"] = existing + added

    counts = Counter(str(edge.get("relation") or "UNKNOWN") for edge in result["edges"])
    stats = dict(result.get("stats") or {})
    stats["edge_count"] = len(result["edges"])
    stats["edge_counts_by_relation"] = dict(sorted(counts.items()))
    stats["verified_claim_relation_count"] = sum(
        relation in {
            "SUPPORTS", "CONTRADICTS", "REPLICATES", "FAILS_TO_REPLICATE",
            "REFINES", "QUALIFIES", "EXTENDS", "USES_METHOD_FROM",
            "BOUNDARY_CONDITION",
        }
        for relation in counts.elements()
    )
    result["stats"] = stats
    provenance = dict(result.get("provenance") or {})
    provenance["claim_relation_projection"] = {
        "schema_version": "claim_relation_v1",
        "input_relation_count": len(relations),
        "projected_relation_count": len(projected),
        "new_edge_count": len(added),
        "policy": "verified_only_with_bilateral_evidence",
    }
    result["provenance"] = provenance
    return result


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--relations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if args.output.resolve() == args.graph.resolve():
        raise SystemExit("output must differ from the source graph")
    if args.output.exists() and not args.replace:
        raise SystemExit(f"output exists; use --replace: {args.output}")
    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    enriched = enrich_graph(graph, read_relations(args.relations))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(args.output, enriched)
    print(json.dumps({
        "output": str(args.output),
        "node_count": len(enriched.get("nodes", [])),
        "edge_count": len(enriched.get("edges", [])),
        "verified_claim_relation_count": enriched["stats"]["verified_claim_relation_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
