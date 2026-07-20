from __future__ import annotations

import json
from pathlib import Path
import shutil

import yaml

from agent_alpha.config import project_path
from agent_alpha.workflows.run_local_paper_to_factor import run_workflow


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, messages):
        self.calls += 1
        if self.calls == 1:
            return {
                "signals": [
                    {
                        "signal_id": "sig_lob_imbalance",
                        "source_paper_id": "paper_demo",
                        "source_reading_note_id": "paper_demo",
                        "signal_name": "LOB imbalance pressure",
                        "market_intuition": "Visible bid depth exceeding ask depth may proxy buying pressure.",
                        "hypothesis": "Top-book imbalance can forecast short-horizon continuation.",
                        "expected_direction": "positive",
                        "hf_mechanism_tags": ["order_book_pressure"],
                        "candidate_fields": ["bidV1", "askV1"],
                        "evidence_ids": ["ev_0001"],
                    }
                ]
            }
        return {
            "factor_candidates": [
                {
                    "factor_id": "lob_imbalance_l1",
                    "name": "lob_imbalance_l1",
                    "prefix_expression": ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]],
                    "expression": "safe_div(bidV1 - askV1, bidV1 + askV1)",
                    "fields": ["bidV1", "askV1"],
                    "windows": [],
                    "direction": "positive",
                    "source_signal_id": "sig_lob_imbalance",
                    "source_reading_note_id": "paper_demo",
                    "mechanism_tags": ["order_book_pressure"],
                }
            ]
        }


def test_e2e_local_paper_to_factor_uses_fake_client(tmp_path: Path) -> None:
    paper = tmp_path / "demo.md"
    paper.write_text(
        """# Limit Order Book Imbalance

This paper studies whether high-frequency limit order book imbalance predicts intraday returns.

## Data

The dataset uses tick data, bid and ask prices, bid and ask depth, spread, volume, and turnover.

## Mechanism

Order imbalance can reflect liquidity pressure because aggressive buying consumes ask depth and may move close prices.

## Formula

Imbalance = (bidV1 - askV1) / (bidV1 + askV1).

## Evidence

The paper reports that visible bid depth exceeding ask depth is associated with short-horizon continuation.
""",
        encoding="utf-8",
    )
    output_dir = tmp_path / "outputs"
    factor_dir = tmp_path / "data" / "factors" / "rendered"
    fac_eval_config = output_dir / "fac_eval_config.yaml"
    client = FakeClient()

    summary = run_workflow(
        paper=paper,
        output_dir=output_dir,
        factor_dir=factor_dir,
        fac_eval_config=fac_eval_config,
        client=client,
    )

    assert client.calls == 2
    assert summary["status"] == "ok"
    assert Path(summary["reading_note"]).exists()
    assert summary["reading_gate"]["should_continue"] is True
    assert Path(summary["signals_path"]).exists()
    assert Path(summary["factor_candidates_path"]).exists()
    rendered = factor_dir / "lob_imbalance_l1.py"
    assert rendered.exists()
    assert str(rendered) in summary["rendered_factor_files"]
    assert fac_eval_config.exists()

    signals = json.loads(Path(summary["signals_path"]).read_text(encoding="utf-8"))
    candidates = json.loads(Path(summary["factor_candidates_path"]).read_text(encoding="utf-8"))
    fac_eval_payload = yaml.safe_load(fac_eval_config.read_text(encoding="utf-8"))
    assert signals["signals"][0]["signal_id"] == "sig_lob_imbalance"
    assert candidates["factor_candidates"][0]["prefix_expression"][0] == "safe_div"
    assert fac_eval_payload["factor_files"][0]["path"] == str(rendered.resolve())
    assert fac_eval_payload["factor_files"][0]["func"] == "compute_factor"

    paper_id = summary["paper_id"]
    shutil.rmtree(project_path("data/raw_papers", paper_id), ignore_errors=True)
    for relative_path in (
        project_path("data/parsed_papers", f"{paper_id}.json"),
        project_path("data/document_chunks", f"{paper_id}.jsonl"),
        project_path("data/reading_notes", f"{paper_id}.json"),
        project_path("data/rma_records", f"{paper_id}.jsonl"),
    ):
        relative_path.unlink(missing_ok=True)