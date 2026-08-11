#!/usr/bin/env python3
"""Score graph research value and select a budget-constrained portfolio."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from paper_graph.graph_value import (
    GraphValueFeaturesV1,
    ResearchPortfolioController,
    assess_graph_value,
)


def read_features(path: Path) -> list[GraphValueFeaturesV1]:
    rows: list[GraphValueFeaturesV1] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(GraphValueFeaturesV1.from_mapping(json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid graph value features at line {line_number}: {exc}") from exc
    return rows


def atomic_write(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="GraphValueFeaturesV1 JSONL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-graphs", type=int, default=10)
    parser.add_argument("--cost-budget", type=float, default=5.0)
    parser.add_argument("--max-per-primary-topic", type=int, default=2)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.replace:
        raise SystemExit(f"output exists; use --replace: {args.output}")

    features = read_features(args.input)
    candidates = [(item, assess_graph_value(item)) for item in features]
    selections = ResearchPortfolioController().select(
        candidates,
        max_graphs=args.max_graphs,
        cost_budget=args.cost_budget,
        max_per_primary_topic=args.max_per_primary_topic,
    )
    output = {
        "schema_version": "research_graph_portfolio_v1",
        "source": str(args.input),
        "policy_version": "graph_value_policy_v1",
        "limits": {
            "max_graphs": args.max_graphs,
            "cost_budget": args.cost_budget,
            "max_per_primary_topic": args.max_per_primary_topic,
        },
        "selected_graph_ids": [
            item.assessment.graph_id for item in selections if item.selected
        ],
        "decisions": [
            {
                "selected": item.selected,
                "selection_reason": item.selection_reason,
                "cumulative_cost": item.cumulative_cost,
                "assessment": item.assessment.to_dict(),
            }
            for item in selections
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(args.output, output)
    print(json.dumps({
        "output": str(args.output),
        "candidate_count": len(selections),
        "selected_count": len(output["selected_graph_ids"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
