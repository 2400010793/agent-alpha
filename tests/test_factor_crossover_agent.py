from __future__ import annotations

from typing import Any

import pytest

from agent_alpha.factors.expression_validator import validate_factor_candidate
from agent_alpha.search.factor_crossover import generate_factor_crossovers


class FakeFactorCrossoverClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.messages: list[dict[str, str]] = []

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.messages = messages
        return self.payload


def _parent_a() -> dict[str, Any]:
    return {
        "factor_id": "lob_imbalance_l1",
        "name": "lob_imbalance_l1",
        "prefix_expression": ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]],
        "expression": "",
        "fields": ["bidV1", "askV1"],
        "windows": [],
        "direction": "positive",
        "source_signal_id": "sig_lob",
        "source_reading_note_id": "note_lob",
        "mechanism_tags": ["order_book_pressure"],
    }


def _parent_b() -> dict[str, Any]:
    return {
        "factor_id": "spread_state",
        "name": "spread_state",
        "prefix_expression": ["zscore", "spread_l1", 60],
        "expression": "",
        "fields": ["spread_l1"],
        "windows": [60],
        "direction": "conditional",
        "source_signal_id": "sig_spread",
        "source_reading_note_id": "note_spread",
        "mechanism_tags": ["spread_liquidity"],
    }


def _payload(prefix_expression: Any | None = None) -> dict[str, Any]:
    prefix = prefix_expression or ["mul", ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]], ["zscore", "spread_l1", 60]]
    return {
        "crossovers": [
            {
                "crossover_id": "cross_lob_spread_confirm",
                "crossover_type": "confirmation_crossover",
                "parent_factor_ids": ["lob_imbalance_l1", "spread_state"],
                "crossed_idea": "LOB imbalance is active only when spread state confirms liquidity stress.",
                "financial_reason": "Raw book imbalance is more credible when liquidity stress confirms that displayed depth matters.",
                "expected_effect": "Reduce false positives from raw top-book imbalance.",
                "combined_components": ["book_imbalance", "spread_state"],
                "kept_from_parent_a": ["book_imbalance"],
                "kept_from_parent_b": ["spread_state"],
                "removed_components": [],
                "risk_note": "May miss pressure when spread is normal.",
                "factor_candidate": {
                    "factor_id": "lob_imbalance_spread_confirm",
                    "name": "lob_imbalance_spread_confirm",
                    "prefix_expression": prefix,
                    "fields": ["bidV1", "askV1", "spread_l1"],
                    "windows": [60],
                    "direction": "conditional",
                    "source_signal_id": "sig_lob",
                    "source_reading_note_id": "note_lob",
                    "mechanism_tags": ["order_book_pressure", "spread_liquidity"],
                    "economic_rationale": "Book pressure is confirmed by liquidity stress.",
                },
            }
        ]
    }


def test_factor_crossover_agent_outputs_valid_factor_candidate() -> None:
    client = FakeFactorCrossoverClient(_payload())

    crossovers = generate_factor_crossovers(_parent_a(), _parent_b(), client, exploration_direction="liquidity confirmation")

    assert len(crossovers) == 1
    child = crossovers[0]
    assert child["created_by"] == "llm_factor_crossover_agent"
    assert child["crossover_type"] == "confirmation_crossover"
    assert child["parent_ids"] == ["lob_imbalance_l1", "spread_state"]
    validation = validate_factor_candidate(child)
    assert validation.ok, validation.message
    assert "Factor Crossover Agent" in client.messages[0]["content"]
    assert "Mandatory format gate" in client.messages[0]["content"]
    assert '{ "crossovers": [] }' in client.messages[0]["content"]
    assert "factor_candidate_format_checker" in client.messages[1]["content"]
    assert "supported_fields_and_asl" in client.messages[1]["content"]


def test_factor_crossover_agent_drops_invalid_output_without_retry() -> None:
    client = FakeFactorCrossoverClient(_payload(["cond", "threshold_value", "volume", "null"]))

    assert generate_factor_crossovers(_parent_a(), _parent_b(), client) == []
    assert len(client.messages) == 2


def test_factor_crossover_agent_rejects_python_code() -> None:
    payload = _payload()
    payload["crossovers"][0]["factor_candidate"]["expression"] = "def compute_factor(code, date, df): pass"
    client = FakeFactorCrossoverClient(payload)

    with pytest.raises(RuntimeError, match="must not contain Python code"):
        generate_factor_crossovers(_parent_a(), _parent_b(), client)