from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import agent_alpha.search.experiment_runner as runner


def _candidate() -> dict[str, Any]:
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
        "economic_rationale": "Visible bid depth exceeding ask depth may proxy buying pressure.",
    }


def test_custom_fac_eval_config_path_is_forwarded_without_tuple(tmp_path: Path, monkeypatch) -> None:
    template = tmp_path / "custom_backtest.yaml"
    template.write_text("output_dir: outputs\n", encoding="utf-8")
    captured: list[str | Path] = []

    def fake_write_fac_eval_config(
        rendered_factor_files: list[str | Path],
        output_path: str | Path,
        *,
        config_path: str | Path,
        overrides: dict[str, Any] | None = None,
    ) -> Path:
        del rendered_factor_files, overrides
        captured.append(config_path)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("output_dir: outputs\n", encoding="utf-8")
        return output

    monkeypatch.setattr(runner, "write_fac_eval_config", fake_write_fac_eval_config)

    runner.run_search_experiment(
        [_candidate()],
        output_dir=tmp_path / "direct",
        fac_eval_config_path=template,
    )

    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(json.dumps({"factor_candidates": [_candidate()]}), encoding="utf-8")
    runner.run_search_experiment_from_file(
        candidates_path,
        output_dir=tmp_path / "from_file",
        fac_eval_config_path=template,
    )

    assert captured == [template, template]
    assert all(not isinstance(value, tuple) for value in captured)