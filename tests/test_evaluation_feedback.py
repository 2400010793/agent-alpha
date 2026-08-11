from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agent_alpha.evaluation.fac_eval_result_reader import read_fac_eval_metrics
from agent_alpha.evaluation.research_evaluator import evaluate_research_quality
from agent_alpha.memory.feedback_memory import append_feedback_record, load_feedback_records, search_feedback_records
from agent_alpha.memory.experiment_memory_writer import build_feedback_memory, write_feedback_memory


def _candidate(**overrides) -> dict:
    candidate = {
        "factor_id": "lob_imbalance_l1",
        "name": "lob_imbalance_l1",
        "prefix_expression": ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]],
        "expression": "safe_div(bidV1 - askV1, bidV1 + askV1)",
        "fields": ["bidV1", "askV1"],
        "windows": [],
        "direction": "positive",
        "source_signal_id": "sig_lob",
        "source_reading_note_id": "note_lob",
        "mechanism_tags": ["order_book_pressure"],
        "economic_rationale": "Visible bid depth exceeding ask depth may proxy short-horizon buying pressure.",
    }
    candidate.update(overrides)
    return candidate


STRONG_METRICS = {
    "daily_rankic": 0.2,
    "finite_ratio": 0.95,
    "zero_ratio": 0.2,
    "qspread_mean": 0.001,
    "n_obs": 10000,
}

WEAK_METRICS = {
    "daily_rankic": 0.001,
    "finite_ratio": 0.95,
    "zero_ratio": 0.2,
    "n_obs": 10000,
}


def test_compile_failed_rejects_candidate() -> None:
    review = evaluate_research_quality(_candidate(), STRONG_METRICS, compile_result={"ok": False, "message": "syntax error"})

    assert review["decision"] == "reject"
    assert "compile_failed" in review["failure_modes"]


def test_validator_failed_or_label_leakage_rejects_candidate() -> None:
    leaky = _candidate(
        prefix_expression=["add", "bidV1", "ret10s"],
        expression="bidV1 + ret10s",
        fields=["bidV1", "ret10s"],
    )

    review = evaluate_research_quality(leaky, STRONG_METRICS, compile_result={"ok": True})

    assert review["decision"] == "reject"
    assert "validator_failed" in review["failure_modes"]
    assert "field_leakage" in review["failure_modes"]


def test_weak_rankic_but_valid_implementation_revises_candidate() -> None:
    review = evaluate_research_quality(_candidate(), WEAK_METRICS, compile_result={"ok": True})

    assert review["decision"] == "revise"
    assert any("rankic_too_weak" in item for item in review["failure_modes"])


def test_strong_rankic_valid_implementation_and_economic_rationale_accepts_candidate() -> None:
    review = evaluate_research_quality(_candidate(), STRONG_METRICS, compile_result={"ok": True})

    assert review["decision"] == "accept"
    assert review["schema_version"] == "research_review_v1"
    assert review["evaluation_record"]["decision"] == "accept"
    assert "rankic_passed_threshold" in review["good_patterns"]


def test_strong_rankic_with_wrong_declared_direction_requires_revision() -> None:
    review = evaluate_research_quality(
        _candidate(direction="positive"),
        {**STRONG_METRICS, "daily_rankic": -0.2},
        compile_result={"ok": True},
    )

    assert review["decision"] == "revise"
    assert any("direction_mismatch" in item for item in review["failure_modes"])


def test_build_feedback_memory_outputs_good_bad_revise_labels() -> None:
    good = evaluate_research_quality(_candidate(), STRONG_METRICS, compile_result={"ok": True})
    bad = evaluate_research_quality(_candidate(), STRONG_METRICS, compile_result={"ok": False})
    revise = evaluate_research_quality(_candidate(), WEAK_METRICS, compile_result={"ok": True})

    assert build_feedback_memory(good, _candidate())["label"] == "GOOD"
    assert build_feedback_memory(bad, _candidate())["label"] == "BAD"
    assert build_feedback_memory(revise, _candidate())["label"] == "REVISE"


def test_write_feedback_memory_writes_jsonl_to_tmp_path(tmp_path: Path) -> None:
    review = evaluate_research_quality(_candidate(), STRONG_METRICS, compile_result={"ok": True})
    record = build_feedback_memory(review, _candidate())
    out = tmp_path / "feedback.jsonl"

    write_feedback_memory(out, [record])

    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows == [record]
    assert not (tmp_path / "data").exists()


def test_feedback_memory_append_load_search_supports_revise(tmp_path: Path) -> None:
    path = tmp_path / "feedback.jsonl"

    record = append_feedback_record(
        {
            "factor_id": "lob_imbalance_l1",
            "label": "revise",
            "failure_type": "weak_rankic",
            "repair_hint": "Try a longer normalization window.",
        },
        path=path,
    )

    assert record["label"] == "REVISE"
    assert load_feedback_records(path)[0]["label"] == "REVISE"
    assert search_feedback_records("longer", path, filters={"label": "REVISE"})[0]["factor_id"] == "lob_imbalance_l1"


def test_read_fac_eval_metrics_json_csv_and_parquet(tmp_path: Path) -> None:
    rows = [{"factor_id": "lob_imbalance_l1", "daily_rankic": 0.2, "finite_ratio": 0.95}]
    json_path = tmp_path / "metrics.json"
    csv_path = tmp_path / "metrics.csv"
    parquet_path = tmp_path / "metrics.parquet"
    json_path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    csv_path.write_text("factor_id,daily_rankic,finite_ratio\nlob_imbalance_l1,0.2,0.95\n", encoding="utf-8")

    assert read_fac_eval_metrics(json_path) == rows
    assert read_fac_eval_metrics(csv_path) == rows

    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    pd.DataFrame(rows).to_parquet(parquet_path, index=False)
    assert read_fac_eval_metrics(parquet_path) == rows


def test_evaluation_feedback_does_not_import_llm_or_run_fac_eval() -> None:
    before = set(sys.modules)
    evaluate_research_quality(_candidate(), STRONG_METRICS, compile_result={"ok": True})
    imported = set(sys.modules) - before

    assert not any(name == "agent_alpha.llm" or name.startswith("agent_alpha.llm.") for name in imported)
    assert not any(name.startswith("py_eval") for name in imported)
