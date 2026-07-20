from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_alpha.llm.client import LLMSettings
from agent_alpha.workflows.batch_factor_iteration import run_batch_factor_iteration


class FakeBatchClient:
    def __init__(self) -> None:
        self.settings = LLMSettings(base_url="https://example.invalid", api_key="fake", model="fake")
        self.calls = 0

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.calls += 1
        system = messages[0]["content"]
        if "Signal Mutation Agent" in system:
            assert "signal_format_checker" in messages[1]["content"]
            return {
                "signal_mutations": [
                    {
                        "mutation_id": "mut_lob_spread_confirm",
                        "mutation_type": "state_condition_mutation",
                        "parent_signal_id": "sig_lob",
                        "parent_idea": "Visible bid depth exceeding ask depth may proxy pressure.",
                        "mutated_idea": "LOB pressure matters more when spread/liquidity state confirms stress.",
                        "financial_reason": "Raw top-book pressure can be noisy without liquidity context.",
                        "expected_effect": "Reduce false positives.",
                        "changed_components": ["state_condition"],
                        "signal": {
                            "signal_id": "sig_lob_spread_confirm",
                            "source_paper_id": "paper_lob",
                            "source_reading_note_id": "note_lob",
                            "signal_name": "LOB pressure with spread confirmation",
                            "market_intuition": "Book pressure is more meaningful when liquidity state confirms stress.",
                            "hypothesis": "Spread-confirmed book pressure predicts continuation.",
                            "expected_direction": "conditional",
                            "hf_mechanism_tags": ["order_book_pressure", "spread_liquidity"],
                            "candidate_fields": ["bidV1", "askV1", "spread_l1"],
                            "evidence_ids": ["ev1"],
                        },
                    }
                ]
            }
        if "Factor Mutation Agent" in system:
            return {
                "mutations": [
                    {
                        "mutation_id": "mut_lob_spread_state",
                        "mutation_type": "state_condition_mutation",
                        "parent_factor_id": "lob_imbalance_l1",
                        "parent_idea": "Visible bid depth exceeding ask depth may proxy pressure.",
                        "mutated_idea": "Book imbalance pressure is active only when liquidity state confirms it.",
                        "financial_reason": "Raw top-book depth alone can be unstable; liquidity confirmation reduces false positives.",
                        "expected_effect": "Improve robustness.",
                        "failure_mode_addressed": "raw_depth_instability",
                        "kept_core_mechanism": "order book pressure",
                        "changed_components": ["state_condition"],
                        "removed_components": [],
                        "risk_note": "May miss pure depth signals.",
                        "factor_candidate": {
                            "factor_id": "lob_imbalance_liquidity_state",
                            "name": "lob_imbalance_liquidity_state",
                            "prefix_expression": ["mul", ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]], ["zscore", "spread_l1", 60]],
                            "fields": ["bidV1", "askV1", "spread_l1"],
                            "windows": [60],
                            "direction": "conditional",
                            "source_signal_id": "sig_lob",
                            "source_reading_note_id": "note_lob",
                            "mechanism_tags": ["order_book_pressure"],
                            "economic_rationale": "Book pressure is conditioned on liquidity state.",
                        },
                    }
                ]
            }
        return {
            "factor_candidates": [
                {
                    "factor_id": "lob_imbalance_l1",
                    "name": "lob_imbalance_l1",
                    "prefix_expression": ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]],
                    "fields": ["bidV1", "askV1"],
                    "windows": [],
                    "direction": "positive",
                    "source_signal_id": "sig_lob",
                    "source_reading_note_id": "note_lob",
                    "mechanism_tags": ["order_book_pressure"],
                    "economic_rationale": "Visible bid depth exceeding ask depth may proxy pressure.",
                }
            ]
        }


def test_batch_factor_iteration_generates_initial_factors_and_llm_mutation(tmp_path: Path) -> None:
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(
        json.dumps(
            {
                "signals": [
                    {
                        "signal_id": "sig_lob",
                        "source_paper_id": "paper_lob",
                        "source_reading_note_id": "note_lob",
                        "signal_name": "LOB pressure",
                        "market_intuition": "Visible bid depth exceeding ask depth may proxy pressure.",
                        "hypothesis": "LOB pressure predicts continuation.",
                        "expected_direction": "positive",
                        "hf_mechanism_tags": ["order_book_pressure"],
                        "candidate_fields": ["bidV1", "askV1"],
                        "evidence_ids": ["ev1"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    summary = run_batch_factor_iteration(
        signals_path,
        output_dir=tmp_path / "run",
        client=FakeBatchClient(),
        generations=2,
        max_candidates_per_signal=1,
        max_signal_mutations_per_signal=1,
        max_new_candidates=2,
    )

    assert summary["status"] == "ok"
    assert summary["signal_count"] == 1
    assert summary["signal_mutation_count"] == 1
    assert summary["factor_input_signal_count"] == 2
    assert summary["initial_candidate_count"] == 2
    assert Path(summary["signal_mutations"]).exists()
    assert Path(summary["initial_candidates"]).exists()
    assert summary["initial_rendered_factor_files"]
    generation_1 = tmp_path / "run" / "iteration" / "generation_1" / "summary.json"
    assert generation_1.exists()
    assert json.loads(generation_1.read_text(encoding="utf-8"))["input_count"] == 1