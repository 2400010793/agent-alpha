from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_alpha.search.experiment_runner import run_search_experiment, run_search_experiment_from_file
from agent_alpha.workflows.enhance_and_backtest_factors import main


class FakeMemorySummaryClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.calls += 1
        return {
            "function_memory": [{"label": "GOOD", "function_pattern": "safe_div book imbalance", "summary": "book imbalance survived review"}],
            "transfer_memory": [{"label": "GOOD", "mutation_type": "state_condition_mutation", "summary": "state conditioning helped"}],
        }


def _candidate() -> dict:
    return {
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


def _metrics(path: Path) -> Path:
    payload = {
        "rows": [
            {
                "factor_id": "lob_imbalance_l1",
                "daily_rankic": 0.2,
                "finite_ratio": 0.95,
                "zero_ratio": 0.2,
                "qspread_mean": 0.001,
                "n_obs": 10000,
            }
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _child_candidate() -> dict:
    return {
        **_candidate(),
        "factor_id": "lob_imbalance_state_child",
        "name": "lob_imbalance_state_child",
        "prefix_expression": ["mul", ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]], ["zscore", "spread_l1", 60]],
        "fields": ["bidV1", "askV1", "spread_l1"],
        "windows": [60],
        "parent_ids": ["lob_imbalance_l1"],
        "mutation_type": "state_condition_mutation",
        "specialist_agent_name": "StateConditionMutationAgent",
        "financial_reason": "Raw book pressure needs liquidity state confirmation.",
    }


def test_run_search_experiment_writes_iteration_artifacts(tmp_path: Path) -> None:
    summary = run_search_experiment([_candidate()], output_dir=tmp_path, metrics_path=_metrics(tmp_path / "metrics.json"), generations=1)

    assert summary["status"] == "ok"
    assert summary["rendered_factor_files"]
    assert Path(summary["candidate_pool"]).exists()
    assert Path(summary["feedback_memory"]).exists()
    assert Path(summary["evaluation_records"]).exists()
    assert Path(summary["manifest"]).exists()
    assert Path(summary["frontier"]).exists()
    assert Path(summary["lineage_states"]).exists()
    assert (tmp_path / "candidates.jsonl").exists()
    assert (tmp_path / "frontier.jsonl").exists()
    assert (tmp_path / "lineage_states.json").exists()
    assert (tmp_path / "evaluations.jsonl").exists()
    assert (tmp_path / "rendered" / "generation_0").exists()
    assert (tmp_path / "reports" / "generation_0").exists()
    assert (tmp_path / "generation_0" / "fac_eval_config.yaml").exists()
    assert (tmp_path / "generation_0" / "summary.json").exists()
    generation_summary = json.loads((tmp_path / "generation_0" / "summary.json").read_text(encoding="utf-8"))
    assert generation_summary["review_count"] == 1
    assert generation_summary["frontier_count"] == 1


def test_run_search_experiment_from_file(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps({"factor_candidates": [_candidate()]}), encoding="utf-8")

    summary = run_search_experiment_from_file(candidates, output_dir=tmp_path / "run", metrics_path=_metrics(tmp_path / "metrics.json"))

    assert summary["status"] == "ok"


def test_enhance_and_backtest_cli(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps({"factor_candidates": [_candidate()]}), encoding="utf-8")
    rc = main([
        "--candidates",
        str(candidates),
        "--output-dir",
        str(tmp_path / "cli_run"),
        "--metrics",
        str(_metrics(tmp_path / "metrics.json")),
    ])

    assert rc == 0
    assert (tmp_path / "cli_run" / "summary.json").exists()


def test_run_search_experiment_uses_fac_eval_metrics_when_available(tmp_path: Path, monkeypatch) -> None:
    import agent_alpha.search.experiment_runner as runner

    def fake_run_fac_eval_config(config_path, *, run_id, **kwargs):
        stock_level = runner._fac_eval_stock_level_path(config_path, run_id)
        stock_level.parent.mkdir(parents=True, exist_ok=True)
        metrics_payload = {
            "rows": [
                {
                    "factor_id": "lob_imbalance_l1",
                    "daily_rankic": 0.2,
                    "finite_ratio": 0.95,
                    "zero_ratio": 0.2,
                    "n_obs": 10000,
                }
            ]
        }
        json_path = stock_level.with_suffix(".json")
        json_path.write_text(json.dumps(metrics_payload), encoding="utf-8")
        # The production path expects stock_level.parquet. For this unit test,
        # patch the metrics reader to read our JSON sidecar through the same lookup.
        stock_level.write_text("placeholder", encoding="utf-8")
        class Proc:
            returncode = 0
            stdout = "ok"
            stderr = ""
        return Proc()

    def fake_metrics_by_factor(path):
        return {"lob_imbalance_l1": {"factor_id": "lob_imbalance_l1", "daily_rankic": 0.2, "finite_ratio": 0.95, "zero_ratio": 0.2, "n_obs": 10000}}

    monkeypatch.setattr(runner, "run_fac_eval_config", fake_run_fac_eval_config)
    monkeypatch.setattr(runner, "_metrics_by_factor", fake_metrics_by_factor)

    summary = run_search_experiment([_candidate()], output_dir=tmp_path / "run_fac", generations=1, run_fac_eval=True)
    generation_summary = json.loads((tmp_path / "run_fac" / "generation_0" / "summary.json").read_text(encoding="utf-8"))

    assert summary["status"] == "ok"
    assert generation_summary["fac_eval_result"]["ok"] is True
    assert generation_summary["fac_eval_metrics_path"].endswith("stock_level.parquet")


def test_run_search_experiment_writes_review_outcome_memory_for_mutation_child(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "rows": [
                    {"factor_id": "lob_imbalance_l1", "daily_rankic": 0.1, "finite_ratio": 0.95, "zero_ratio": 0.2, "n_obs": 10000},
                    {"factor_id": "lob_imbalance_state_child", "daily_rankic": 0.2, "finite_ratio": 0.95, "zero_ratio": 0.2, "n_obs": 10000},
                ]
            }
        ),
        encoding="utf-8",
    )

    summary = run_search_experiment([_candidate(), _child_candidate()], output_dir=tmp_path / "run", metrics_path=metrics_path, generations=1, memory_consolidation_records=1)

    assert summary["status"] == "ok"
    arm_memory = tmp_path / "run" / "memory" / "mutation_arm_memory.jsonl"
    transfer_memory = tmp_path / "run" / "memory" / "transfer_memory.jsonl"
    assert arm_memory.exists()
    assert transfer_memory.exists()
    arm_record = json.loads(arm_memory.read_text(encoding="utf-8").splitlines()[0])
    assert arm_record["child_factor_id"] == "lob_imbalance_state_child"
    assert arm_record["success"] is True
    generation_summary = json.loads((tmp_path / "run" / "generation_0" / "summary.json").read_text(encoding="utf-8"))
    assert generation_summary["memory_consolidation"]["consolidated"]


def test_run_search_experiment_can_summarize_generation_memory_with_llm(tmp_path: Path) -> None:
    client = FakeMemorySummaryClient()

    summary = run_search_experiment(
        [_candidate()],
        output_dir=tmp_path / "run",
        metrics_path=_metrics(tmp_path / "metrics.json"),
        generations=1,
        client=client,  # type: ignore[arg-type]
        summarize_generation_memory=True,
    )

    assert summary["status"] == "ok"
    assert client.calls == 1
    assert (tmp_path / "run" / "memory" / "function_memory.jsonl").exists()
    assert (tmp_path / "run" / "memory" / "transfer_memory.jsonl").exists()
    assert (tmp_path / "run" / "manifest.json").exists()