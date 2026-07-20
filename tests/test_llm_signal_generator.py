from __future__ import annotations

import json
from pathlib import Path

from agent_alpha.memory.feedback_memory import append_feedback_record
from agent_alpha.signals.llm_signal_generator import generate_signals_from_reading_note
from agent_alpha.signals.signal_ranker import rank_signals
from agent_alpha.signals.signal_schema import validate_alpha_signal
from agent_alpha.signals.signal_store import append_signals_jsonl, load_signals_json, load_signals_jsonl, write_signals_json


class FakeSignalClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0
        self.messages = []

    def complete_json(self, messages):
        self.calls += 1
        self.messages = messages
        return self.payload


def _reading_note() -> dict:
    return {
        "schema_version": "reading_note_v1",
        "paper_id": "paper_demo",
        "supporting_evidence": [{"evidence_id": "ev_0001"}],
        "possible_trading_intuitions": ["Order-book pressure may forecast continuation."],
    }


def test_llm_signal_generator_filters_local_schema_and_never_calls_external_api() -> None:
    client = FakeSignalClient(
        {
            "signals": [
                {
                    "signal_id": "sig_lob_imbalance",
                    "source_paper_id": "paper_demo",
                    "source_reading_note_id": "note_demo",
                    "signal_name": "LOB imbalance pressure",
                    "market_intuition": "Visible bid depth exceeding ask depth may proxy buying pressure.",
                    "hypothesis": "Top-book imbalance can forecast short-horizon continuation.",
                    "expected_direction": "positive",
                    "hf_mechanism_tags": ["order_book_pressure", "not_a_mechanism"],
                    "candidate_fields": ["bidV1", "askV1", "ret60s", "industry", "unknown_field"],
                    "evidence_ids": ["ev_0001"],
                }
            ]
        }
    )

    signals = generate_signals_from_reading_note(_reading_note(), client)

    assert client.calls == 1
    assert len(signals) == 1
    signal = signals[0]
    validate_alpha_signal(signal)
    assert signal["hf_mechanism_tags"] == ["order_book_pressure"]
    assert signal["candidate_fields"] == ["bidV1", "askV1"]
    assert "ret60s" not in signal["candidate_fields"]
    assert "industry" not in signal["candidate_fields"]
    assert "unknown_field" not in signal["candidate_fields"]
    prompt_payload = json.loads(client.messages[1]["content"])
    assert "ret60s" in prompt_payload["label_fields_forbidden"]
    assert "output_format" in prompt_payload
    assert "Agent Alpha The Idea Person" in client.messages[0]["content"]
    assert "Do not generate factor expressions" in client.messages[0]["content"]


def test_llm_signal_generator_injects_good_bad_memory(tmp_path: Path) -> None:
    feedback_path = tmp_path / "feedback.jsonl"
    append_feedback_record(
        {
            "factor_id": "good_lob",
            "label": "GOOD",
            "reusable_principle": "Reuse imbalance only when supported by spread/liquidity evidence.",
        },
        path=feedback_path,
    )
    append_feedback_record(
        {
            "factor_id": "bad_lob",
            "label": "BAD",
            "avoid_rule": "Avoid signals that rely on top-book depth alone without liquidity context.",
        },
        path=feedback_path,
    )
    client = FakeSignalClient({"signals": []})

    generate_signals_from_reading_note(_reading_note(), client, feedback_memory_path=feedback_path)

    prompt_payload = json.loads(client.messages[1]["content"])
    memory = prompt_payload["prompt_context"]["good_bad_memory"]
    assert "Reuse imbalance" in memory["reuse_principles"][0]
    assert "Avoid signals" in memory["avoid_rules"][0]
    assert prompt_payload["prompt_context"]["skill_rules"]
    assert prompt_payload["prompt_context"]["shared_constraints"]


def test_llm_signal_generator_empty_signals_is_ok() -> None:
    client = FakeSignalClient({"signals": []})

    assert generate_signals_from_reading_note(_reading_note(), client) == []
    assert client.calls == 1


def test_rank_signals_prefers_evidence_fields_tags_and_text() -> None:
    weak = {
        "signal_id": "weak",
        "evidence_ids": [],
        "candidate_fields": ["bidV1"],
        "hf_mechanism_tags": [],
        "market_intuition": "",
        "hypothesis": "",
    }
    strong = {
        "signal_id": "strong",
        "evidence_ids": ["ev1", "ev2"],
        "candidate_fields": ["bidV1", "askV1"],
        "hf_mechanism_tags": ["order_book_pressure"],
        "market_intuition": "intuition",
        "hypothesis": "hypothesis",
    }

    assert rank_signals([weak, strong])[0]["signal_id"] == "strong"


def test_signal_store_writes_json_and_jsonl(tmp_path: Path) -> None:
    client = FakeSignalClient(
        {
            "signals": [
                {
                    "signal_id": "sig_lob_imbalance",
                    "source_paper_id": "paper_demo",
                    "source_reading_note_id": "note_demo",
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
    )
    signals = generate_signals_from_reading_note(_reading_note(), client)
    json_path = write_signals_json(tmp_path / "signals.json", signals)
    jsonl_path = append_signals_jsonl(tmp_path / "signals.jsonl", signals)

    assert load_signals_json(json_path)[0]["signal_id"] == "sig_lob_imbalance"
    assert load_signals_jsonl(jsonl_path)[0]["candidate_fields"] == ["bidV1", "askV1"]