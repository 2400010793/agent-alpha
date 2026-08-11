from __future__ import annotations

from pathlib import Path

import pytest

from agent_alpha.library.alpha_library import append_alpha_record, build_alpha_record, load_alpha_records, search_elite


def test_alpha_library_admits_only_accepted_record_above_configured_threshold(tmp_path: Path) -> None:
    path = tmp_path / "alpha_library.jsonl"

    record = append_alpha_record(
        {
            "factor_id": "lob_imbalance_l1",
            "name": "lob_imbalance_l1",
            "decision": "accept",
            "metrics": {"daily_rankic": 0.2, "finite_ratio": 0.95},
            "mechanism_tags": ["order_book_pressure"],
            "summary": "Elite top-book pressure alpha.",
        },
        path=path,
    )

    assert record["status"] == "admitted"
    assert record["performance_score"] == 0.2
    assert load_alpha_records(path)[0]["factor_id"] == "lob_imbalance_l1"
    assert search_elite("top-book", path=path)[0]["factor_id"] == "lob_imbalance_l1"


def test_alpha_library_rejects_records_without_performance_metric(tmp_path: Path) -> None:
    path = tmp_path / "alpha_library.jsonl"

    with pytest.raises(ValueError, match="performance metric"):
        append_alpha_record(
            {"factor_id": "missing_metric", "decision": "accept", "metrics": {"finite_ratio": 0.95}},
            path=path,
        )


def test_alpha_library_rejects_duplicate_canonical_factor(tmp_path: Path) -> None:
    path = tmp_path / "alpha_library.jsonl"
    record = {
        "factor_id": "lob_imbalance_l1",
        "name": "lob_imbalance_l1",
        "decision": "accept",
        "metrics": {"daily_rankic": 0.2, "finite_ratio": 0.95},
        "prefix_expression": ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]],
        "fields": ["bidV1", "askV1"],
        "mechanism_tags": ["order_book_pressure"],
    }

    append_alpha_record(record, path=path)

    with pytest.raises(ValueError, match="duplicate alpha"):
        append_alpha_record({**record, "factor_id": "same_formula_other_name", "name": "same_formula_other_name"}, path=path)

def test_build_alpha_record_preserves_mutation_lineage_metadata(tmp_path: Path) -> None:
    path = tmp_path / "alpha_library.jsonl"
    candidate = {
        "factor_id": "child_depth_state",
        "name": "child_depth_state",
        "prefix_expression": ["mul", ["zscore", "depth_imbalance_l1", 60], ["zscore", "spread_l1", 60]],
        "fields": ["depth_imbalance_l1", "spread_l1"],
        "windows": [60],
        "direction": "conditional",
        "mechanism_tags": ["order_book_pressure", "spread_liquidity"],
        "parent_ids": ["parent_depth"],
        "mutation_type": "state_condition_mutation",
        "specialist_agent_name": "StateConditionMutationAgent",
    }
    review = {"factor_id": "child_depth_state", "factor_name": "child_depth_state", "decision": "accept", "metrics": {"daily_rankic": 0.2, "finite_ratio": 0.95}}

    record = append_alpha_record(build_alpha_record(candidate, review), path=path)

    assert record["status"] == "admitted"
    assert record["prefix_expression"] == candidate["prefix_expression"]
    assert record["parent_ids"] == ["parent_depth"]
    assert record["mutation_type"] == "state_condition_mutation"
    assert record["specialist_agent_name"] == "StateConditionMutationAgent"
