#!/usr/bin/env python3
"""Build one graph-conditioned Agent Alpha intake package completely offline."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from paper_graph.claim_relations import ClaimRelationV1
from paper_graph.graph_value import GraphValueFeaturesV1, assess_graph_value
from paper_graph.research_contracts import canonical_hash
from paper_graph.research_opportunity import (
    StructuredPaperArtifactRefV1,
    build_factor_research_package,
    build_research_opportunity,
)


def read_jsonl(path: Path | None, factory: Any) -> list[Any]:
    if path is None:
        return []
    result = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            result.append(factory(json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid record at {path}:{line_number}: {exc}") from exc
    return result


def atomic_write(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--graph-features", type=Path, required=True)
    parser.add_argument("--structured-artifacts", type=Path, required=True)
    parser.add_argument("--claim-relations", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--taxonomy-version", required=True)
    parser.add_argument("--research-question", required=True)
    parser.add_argument("--required-observable", action="append", default=[])
    parser.add_argument("--producer-revision", required=True)
    parser.add_argument("--config-hash", required=True)
    parser.add_argument("--data-contract-id", required=True)
    parser.add_argument("--data-contract-hash", required=True)
    parser.add_argument("--field-registry-version", required=True)
    parser.add_argument("--operator-registry-version", required=True)
    parser.add_argument("--memory-snapshot-id", required=True)
    parser.add_argument("--research-budget-file", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    known_outputs = (
        "manifest.json", "graph_value_assessment.json", "research_opportunity.json",
        "factor_research_package.json", "evidence_queue.json", "needs_data_queue.json",
        "human_review_queue.json",
    )
    if args.output_dir.exists() and not args.replace and any(
        (args.output_dir / name).exists() for name in known_outputs
    ):
        raise SystemExit(f"intake output exists; use --replace: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    features = GraphValueFeaturesV1.from_mapping(
        json.loads(args.graph_features.read_text(encoding="utf-8"))
    )
    assessment = assess_graph_value(features)
    graph_id = str(graph.get("graph_id") or graph.get("category") or "")
    if graph_id != features.graph_id:
        raise ValueError("graph_id differs between graph and graph value features")
    artifacts = read_jsonl(
        args.structured_artifacts, StructuredPaperArtifactRefV1.from_mapping
    )
    relations = read_jsonl(args.claim_relations, ClaimRelationV1.from_mapping)
    opportunity = build_research_opportunity(
        graph,
        artifacts,
        relations,
        assessment,
        as_of_date=args.as_of_date,
        taxonomy_version=args.taxonomy_version,
        research_question=args.research_question,
        required_observables=args.required_observable,
        producer_revision=args.producer_revision,
        config_hash=args.config_hash,
        prior_art_search_trace={"status": "not_provided", "as_of_date": args.as_of_date},
    )
    budget = json.loads(args.research_budget_file.read_text(encoding="utf-8"))
    atomic_write(args.output_dir / "graph_value_assessment.json", assessment.to_dict())
    atomic_write(args.output_dir / "research_opportunity.json", opportunity.to_dict())
    package = None
    queue_file = None
    if opportunity.status == "READY":
        package = build_factor_research_package(
            opportunity,
            target_track=features.target_track,
            data_contract_id=args.data_contract_id,
            data_contract_hash=args.data_contract_hash,
            field_registry_version=args.field_registry_version,
            operator_registry_version=args.operator_registry_version,
            memory_snapshot_id=args.memory_snapshot_id,
            research_budget=budget,
            selection_trace={
                "assessment_id": assessment.assessment_id,
                "score": assessment.score,
                "priority_tier": assessment.priority_tier,
                "recommended_action": assessment.recommended_action,
            },
        )
        atomic_write(args.output_dir / "factor_research_package.json", package.to_dict())
    else:
        queue_file = {
            "EVIDENCE_QUEUE": "evidence_queue.json",
            "NEEDS_DATA": "needs_data_queue.json",
            "METHOD_REVIEW": "human_review_queue.json",
            "HUMAN_REVIEW": "human_review_queue.json",
        }[opportunity.status]
        atomic_write(args.output_dir / queue_file, opportunity.to_dict())
    manifest = {
        "schema_version": "auto_research_intake_manifest_v1",
        "graph_source": str(args.graph),
        "graph_source_hash": canonical_hash(graph),
        "structured_artifact_source": str(args.structured_artifacts),
        "claim_relation_source": str(args.claim_relations) if args.claim_relations else None,
        "assessment_id": assessment.assessment_id,
        "research_opportunity_id": opportunity.research_opportunity_id,
        "package_id": package.package_id if package else None,
        "status": opportunity.status,
        "queue_file": queue_file,
    }
    atomic_write(args.output_dir / "manifest.json", manifest)
    print(json.dumps({
        "output_dir": str(args.output_dir),
        "research_opportunity_id": opportunity.research_opportunity_id,
        "status": opportunity.status,
        "package_id": package.package_id if package else None,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
