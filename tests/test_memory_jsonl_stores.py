from __future__ import annotations

from pathlib import Path

import pytest

from agent_alpha.factors.factor_store import append_factor_record, load_factor_records, search_factor_records
from agent_alpha.library.alpha_library import append_alpha_record, load_alpha_records, search_elite
from agent_alpha.memory.balanced_memory import select_balanced_memory
from agent_alpha.memory.evaluation_store import append_evaluation_record, load_evaluation_records, search_evaluation_records
from agent_alpha.memory.feedback_memory import append_feedback_record, load_feedback_records, search_feedback_records
from agent_alpha.memory.function_memory import append_function_memory, load_function_memory, search_function_memory
from agent_alpha.memory.transfer_memory import append_transfer_memory, load_transfer_memory, search_transfer_memory


def test_factor_registry_append_load_search(tmp_path: Path) -> None:
    path = tmp_path / "factor_registry.jsonl"
    record = append_factor_record(
        {
            "factor_id": "lob_imbalance_l1",
            "expression": "safe_div(bidV1 - askV1, bidV1 + askV1)",
            "fields": ["bidV1", "askV1"],
            "mechanism_tags": ["order_book_pressure"],
            "hypothesis": "Top-book imbalance predicts continuation.",
        },
        path=path,
    )

    assert record["schema_version"] == "factor_registry_record_v1"
    assert record["factor_record_id"]
    assert record["name"] == "lob_imbalance_l1"
    assert load_factor_records(path)[0]["factor_id"] == "lob_imbalance_l1"
    assert search_factor_records("top-book", path)[0]["factor_id"] == "lob_imbalance_l1"
    assert search_factor_records("", path, filters={"mechanism_tags": "order_book_pressure"})


def test_evaluation_records_append_load_search(tmp_path: Path) -> None:
    path = tmp_path / "evaluations.jsonl"
    append_evaluation_record(
        {
            "factor_id": "lob_imbalance_l1",
            "run_id": "run_001",
            "decision": "accept",
            "retain_status": "candidate",
            "metrics": {"rankic": 0.2, "finite_ratio": 0.96},
            "leakage_check": "passed",
        },
        path=path,
    )

    assert load_evaluation_records(path, filters={"decision": "accept"})[0]["run_id"] == "run_001"
    assert search_evaluation_records("passed", path)[0]["factor_id"] == "lob_imbalance_l1"


def test_feedback_memory_append_load_search(tmp_path: Path) -> None:
    path = tmp_path / "feedback.jsonl"
    append_feedback_record(
        {
            "factor_id": "lob_imbalance_l1",
            "label": "bad",
            "failure_type": "unstable_ic",
            "avoid_rule": "Avoid using thin top-book depth alone in illiquid names.",
            "repair_hint": "Add spread liquidity control.",
        },
        path=path,
    )

    assert load_feedback_records(path)[0]["label"] == "BAD"
    assert search_feedback_records("illiquid", path, filters={"label": "BAD"})[0]["failure_type"] == "unstable_ic"


def test_feedback_memory_rejects_unknown_label(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="feedback label"):
        append_feedback_record({"label": "maybe"}, path=tmp_path / "feedback.jsonl")


def test_function_memory_append_load_search(tmp_path: Path) -> None:
    path = tmp_path / "function_memory.jsonl"
    append_function_memory(
        {
            "label": "BAD",
            "function_pattern": "zscore(volume,60)",
            "asl_ops": ["zscore"],
            "fields": ["volume"],
            "summary": "Raw volume zscore often measures activity rather than pressure.",
            "repair_hint": "Add price confirmation.",
        },
        path=path,
    )

    assert load_function_memory(path)[0]["schema_version"] == "function_memory_v1"
    assert search_function_memory("price confirmation", path)[0]["fields"] == ["volume"]


def test_transfer_memory_append_load_search(tmp_path: Path) -> None:
    path = tmp_path / "transfer_memory.jsonl"
    append_transfer_memory(
        {
            "label": "GOOD",
            "mutation_type": "state_condition_mutation",
            "from_pattern": "raw book imbalance",
            "to_pattern": "spread-conditioned book imbalance",
            "agent_name": "StateConditionMutationAgent",
            "summary": "Spread state filtered noisy top-book pressure.",
        },
        path=path,
    )

    assert load_transfer_memory(path)[0]["schema_version"] == "transfer_memory_v1"
    assert search_transfer_memory("spread", path)[0]["agent_name"] == "StateConditionMutationAgent"


def test_balanced_memory_selection_uses_positive_warning_recent_and_explore() -> None:
    records = [
        {"memory_id": "good_1", "label": "GOOD", "summary": "spread state helped", "delta_score": 0.03, "updated_at": "2026-01-01T00:00:00+00:00"},
        {"memory_id": "good_2", "label": "GOOD", "summary": "spread liquidity worked", "delta_score": 0.02, "updated_at": "2026-01-02T00:00:00+00:00"},
        {"memory_id": "bad_1", "label": "BAD", "summary": "spread state failed when stale", "delta_score": -0.01, "updated_at": "2026-01-03T00:00:00+00:00"},
        {"memory_id": "recent_1", "label": "NEUTRAL", "summary": "recent rhythm idea", "updated_at": "2026-01-10T00:00:00+00:00"},
        {"memory_id": "explore_1", "label": "NEUTRAL", "summary": "rare book shape", "usage_count": 0, "updated_at": "2026-01-04T00:00:00+00:00"},
        {"memory_id": "overused", "label": "GOOD", "summary": "spread overused", "usage_count": 99, "updated_at": "2026-01-05T00:00:00+00:00"},
    ]

    selected = select_balanced_memory(records, query="spread", kind="transfer", limit=5, seed_text="stable")
    selected_ids = {record["memory_id"] for record in selected}

    assert "good_1" in selected_ids
    assert "bad_1" in selected_ids
    assert "recent_1" in selected_ids
    assert len(selected) == 5


def test_alpha_library_append_load_search(tmp_path: Path) -> None:
    path = tmp_path / "alpha_library.jsonl"
    alpha = append_alpha_record(
        {
            "factor_id": "lob_imbalance_l1",
            "name": "lob_imbalance_l1",
            "decision": "accept",
            "metrics": {"rankic": 0.2, "finite_ratio": 0.96},
            "mechanism_tags": ["order_book_pressure"],
            "summary": "Elite top-book pressure alpha.",
        },
        path=path,
    )

    assert alpha["schema_version"] == "alpha_library_record_v1"
    assert alpha["status"] == "admitted"
    assert load_alpha_records(path)[0]["factor_id"] == "lob_imbalance_l1"
    assert search_elite("top-book", path=path)[0]["factor_id"] == "lob_imbalance_l1"


def test_alpha_library_rejects_unaccepted_or_weak_records(tmp_path: Path) -> None:
    path = tmp_path / "alpha_library.jsonl"
    with pytest.raises(ValueError, match="accepted"):
        append_alpha_record({"factor_id": "bad", "decision": "reject"}, path=path)
    with pytest.raises(ValueError, match="rankic"):
        append_alpha_record({"factor_id": "weak", "decision": "accept", "metrics": {"rankic": 0.001, "finite_ratio": 0.99}}, path=path)