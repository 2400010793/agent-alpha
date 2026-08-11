from __future__ import annotations

import importlib.util
import py_compile
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from agent_alpha.factors.expression_validator import validate_factor_candidate
from agent_alpha.factors.fac_eval_adapter import py_compile_factor_file, write_fac_eval_config
from agent_alpha.factors.factor_file_renderer import render_factor_file
from agent_alpha.factors.factor_schema import FactorCandidate
from agent_alpha.factors.factor_calculator import calculate_factor_values


def test_factor_candidate_renders_fac_eval_file(tmp_path: Path) -> None:
    candidate = FactorCandidate(
        factor_id="lob_imbalance_l1",
        name="lob_imbalance_l1",
        expression="safe_div(bidV1 - askV1, bidV1 + askV1)",
        fields=["bidV1", "askV1"],
        windows=[],
        direction="positive",
    )

    validation = validate_factor_candidate(candidate)
    assert validation.ok, validation.message

    rendered = render_factor_file(candidate, tmp_path)
    assert rendered.exists()
    text = rendered.read_text(encoding="utf-8")
    assert 'fields = [\'lob_imbalance_l1\']' in text
    assert "def compute_factor" in text
    py_compile.compile(str(rendered), doraise=True)


def test_prefix_factor_candidate_renders_fac_eval_file(tmp_path: Path) -> None:
    candidate = FactorCandidate(
        factor_id="lob_imbalance_prefix",
        name="lob_imbalance_prefix",
        expression="",
        prefix_expression=["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]],
        fields=["bidV1", "askV1"],
        windows=[],
        direction="positive",
    )

    validation = validate_factor_candidate(candidate)
    assert validation.ok, validation.message
    rendered = render_factor_file(candidate, tmp_path)
    assert rendered.exists()
    py_compile.compile(str(rendered), doraise=True)


def test_prefix_factor_candidate_renders_nested_fac_study_ops(tmp_path: Path) -> None:
    candidate = FactorCandidate(
        factor_id="fac_study_nested_prefix",
        name="fac_study_nested_prefix",
        expression="",
        prefix_expression=[
            "where",
            ["gt", ["rolling_std", "close", 20], ["rolling_std", "close", 60]],
            ["div_mean", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"], 30],
            ["neg", ["ewm_mean", ["diff", "volume", 1], 20]],
        ],
        fields=["close", "bidV1", "askV1", "volume"],
        windows=[1, 20, 30, 60],
        direction="conditional",
    )

    validation = validate_factor_candidate(candidate)
    assert validation.ok, validation.message
    rendered = render_factor_file(candidate, tmp_path)
    assert rendered.exists()
    py_compile.compile(str(rendered), doraise=True)


def test_local_calculator_matches_rendered_nested_asl(tmp_path: Path) -> None:
    candidate = {
        "factor_id": "nested_parity",
        "name": "nested_parity",
        "prefix_expression": [
            "where",
            ["gt", ["rolling_mean", "close", 2], "close"],
            ["div_mean", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"], 2],
            ["neg", ["ewm_mean", ["diff", "volume", 1], 2]],
        ],
        "fields": ["close", "bidV1", "askV1", "volume"],
        "windows": [1, 2],
        "direction": "conditional",
    }
    rows = [
        {"close": 10.0, "bidV1": 6.0, "askV1": 4.0, "volume": 100.0},
        {"close": 8.0, "bidV1": 7.0, "askV1": 3.0, "volume": 120.0},
        {"close": 9.0, "bidV1": 5.0, "askV1": 5.0, "volume": 90.0},
    ]

    rendered = render_factor_file(candidate, tmp_path)
    spec = importlib.util.spec_from_file_location("nested_parity_factor", rendered)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rendered_values = module.compute_factor("demo", "2020-01-01", pd.DataFrame(rows))["nested_parity"].to_numpy()
    local_values = np.asarray([record["value"] for record in calculate_factor_values(candidate, rows)], dtype=float)

    np.testing.assert_allclose(local_values, rendered_values, equal_nan=True)


def test_factor_candidate_rejects_label_leakage() -> None:
    candidate = FactorCandidate(
        factor_id="bad_label",
        name="bad_label",
        expression="rolling_mean(ret60s, 20)",
        fields=["ret60s"],
        windows=[20],
    )

    validation = validate_factor_candidate(candidate)
    assert not validation.ok
    assert "forward label leakage" in validation.message


def test_write_fac_eval_config_for_rendered_file(tmp_path: Path) -> None:
    factor_file = tmp_path / "factor.py"
    factor_file.write_text("fields = ['x']\ndef compute_factor(code, date, df):\n    return df\n", encoding="utf-8")
    config_path = write_fac_eval_config([factor_file], tmp_path / "fac_eval.yaml")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert payload["factor_files"][0]["path"] == str(factor_file.resolve())
    assert payload["factor_files"][0]["func"] == "compute_factor"


def test_py_compile_factor_file_reports_success(tmp_path: Path) -> None:
    factor_file = tmp_path / "factor.py"
    factor_file.write_text("fields = ['x']\ndef compute_factor(code, date, df):\n    return df\n", encoding="utf-8")
    result = py_compile_factor_file(factor_file)
    assert result.returncode == 0
