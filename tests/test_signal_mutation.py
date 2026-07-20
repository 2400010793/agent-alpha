from __future__ import annotations

from typing import Any

from agent_alpha.search.signal_mutation import generate_signal_mutations
from agent_alpha.signals.signal_schema import validate_alpha_signal


class FakeSignalMutationClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.messages: list[dict[str, str]] = []

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.messages = messages
        return self.payload


def _parent_signal() -> dict[str, Any]:
    return {
        "signal_id": "sig_volume_shock",
        "source_paper_id": "paper_demo",
        "source_reading_note_id": "note_demo",
        "signal_name": "Volume shock pressure",
        "market_intuition": "Volume shock may indicate short-horizon pressure.",
        "hypothesis": "Large volume predicts continuation.",
        "expected_direction": "positive",
        "hf_mechanism_tags": ["trade_impact"],
        "candidate_fields": ["volume", "money"],
        "evidence_ids": ["ev1"],
    }


def test_signal_mutation_agent_outputs_mutated_signal() -> None:
    client = FakeSignalMutationClient(
        {
            "signal_mutations": [
                {
                    "mutation_id": "mut_price_confirmed_volume",
                    "mutation_type": "event_definition_mutation",
                    "parent_signal_id": "sig_volume_shock",
                    "parent_idea": "Volume shock may indicate short-horizon pressure.",
                    "mutated_idea": "Volume shock is treated as pressure only when price confirms the activity.",
                    "financial_reason": "Activity without price confirmation may be absorption rather than pressure.",
                    "expected_effect": "Reduce false positives from absorbed volume spikes.",
                    "changed_components": ["event_definition", "price_confirmation"],
                    "signal": {
                        "signal_id": "sig_volume_price_confirm",
                        "source_paper_id": "paper_demo",
                        "source_reading_note_id": "note_demo",
                        "signal_name": "Volume shock with price confirmation",
                        "market_intuition": "Volume shock plus price confirmation may proxy informed pressure.",
                        "hypothesis": "Confirmed volume shock forecasts continuation.",
                        "expected_direction": "positive",
                        "hf_mechanism_tags": ["trade_impact", "not_allowed"],
                        "candidate_fields": ["volume", "close", "ret60s"],
                        "evidence_ids": ["ev1"],
                    },
                }
            ]
        }
    )

    mutations = generate_signal_mutations(_parent_signal(), client, exploration_direction="price confirmation")

    assert len(mutations) == 1
    assert mutations[0]["mutation_type"] == "event_definition_mutation"
    assert "price confirms" in mutations[0]["mutated_idea"]
    signal = mutations[0]["signal"]
    validate_alpha_signal(signal)
    assert signal["hf_mechanism_tags"] == ["trade_impact"]
    assert "ret60s" not in signal["candidate_fields"]
    assert "Signal Mutation Agent" in client.messages[0]["content"]
    assert "Mandatory format gate" in client.messages[0]["content"]
    assert '{ "signal_mutations": [] }' in client.messages[0]["content"]
    assert "signal_format_checker" in client.messages[1]["content"]
    assert "Required Signal Shape" in client.messages[1]["content"]


def test_signal_mutation_agent_drops_invalid_signal_without_retry() -> None:
    client = FakeSignalMutationClient(
        {
            "signal_mutations": [
                {
                    "mutation_id": "bad_empty_signal",
                    "mutation_type": "event_definition_mutation",
                    "parent_signal_id": "sig_volume_shock",
                    "parent_idea": "Volume shock may indicate pressure.",
                    "mutated_idea": "Bad empty signal.",
                    "financial_reason": "Should be dropped.",
                    "expected_effect": "None.",
                    "changed_components": ["event_definition"],
                    "signal": {
                        "signal_id": "",
                        "signal_name": "",
                        "market_intuition": "",
                        "hypothesis": "",
                        "expected_direction": "sideways",
                        "hf_mechanism_tags": ["invented_tag"],
                        "candidate_fields": ["ret60s", "invented_field"],
                        "evidence_ids": [],
                    },
                }
            ]
        }
    )

    assert generate_signal_mutations(_parent_signal(), client) == []
    assert len(client.messages) == 2