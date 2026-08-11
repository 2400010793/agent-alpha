from __future__ import annotations

import json
import math

from agent_alpha.agents.runtime_agent import run_runtime_agent
from agent_alpha.config import load_project_config
from agent_alpha.factors.factor_calculator import calculate_factor_values
from agent_alpha.library.deployment_registry import load_deployments, register_deployment
from agent_alpha.workflows.generate_signals_from_papers import main
from agent_alpha.workflows.evaluate_research_quality import main as evaluate_quality_main


class FakeRuntimeClient:
    def complete_json(self, messages: list[dict[str, str]]) -> dict:
        return {"ok": True, "message_count": len(messages)}


def test_load_project_config() -> None:
    config = load_project_config()
    assert config.field_registry["schema_version"] == "hf_field_registry_v2"
    assert "askP1" in config.field_registry["allowed_input_fields"]
    assert "mid_price_l1" in config.field_registry["derived_feature_fields"]


def test_generate_signals_dry_run(capsys) -> None:
    rc = main(["--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "The Idea Person" in out
    assert "paper crawling is skipped" in out


def test_runtime_agent_runs_json_prompt() -> None:
    result = run_runtime_agent(client=FakeRuntimeClient(), system_prompt="Return JSON.", payload={"task": "demo"})  # type: ignore[arg-type]

    assert result == {"ok": True, "message_count": 2}


def test_factor_calculator_local_smoke() -> None:
    candidate = {"factor_id": "book_pressure", "prefix_expression": ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]]}
    rows = [{"bidV1": 3.0, "askV1": 1.0}, {"bidV1": 1.0, "askV1": 3.0}]

    values = calculate_factor_values(candidate, rows)

    assert math.isclose(values[0]["value"], 0.5)
    assert math.isclose(values[1]["value"], -0.5)


def test_deployment_registry_registers_metadata(tmp_path) -> None:
    path = tmp_path / "deployments.jsonl"
    record = register_deployment({"factor_id": "book_pressure", "environment": "paper"}, path=path)

    assert record["schema_version"] == "deployment_registry_record_v1"
    assert load_deployments(path)[0]["factor_id"] == "book_pressure"


def test_evaluate_research_quality_cli_writes_report(tmp_path, capsys) -> None:
    factor = tmp_path / "factor.json"
    metrics = tmp_path / "metrics.json"
    report = tmp_path / "review.json"
    factor.write_text(
        json.dumps(
            {
                "factor_id": "lob_imbalance_l1",
                "name": "lob_imbalance_l1",
                "prefix_expression": ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]],
                "fields": ["bidV1", "askV1"],
                    "direction": "positive",
                    "mechanism_tags": ["order_book_pressure"],
                "economic_rationale": "Visible bid depth exceeding ask depth may proxy pressure.",
            }
        ),
        encoding="utf-8",
    )
    metrics.write_text(json.dumps({"daily_rankic": 0.2, "finite_ratio": 0.95, "zero_ratio": 0.2, "n_obs": 10000}), encoding="utf-8")

    rc = evaluate_quality_main(["--factor", str(factor), "--metrics", str(metrics), "--output", str(report)])

    assert rc == 0
    assert json.loads(report.read_text(encoding="utf-8"))["decision"] == "accept"
    assert "lob_imbalance_l1" in capsys.readouterr().out
