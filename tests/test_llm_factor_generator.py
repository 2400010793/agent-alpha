from __future__ import annotations

import py_compile
import json
from pathlib import Path
from typing import Any

import pytest

from agent_alpha.factors.factor_file_renderer import render_factor_file
from agent_alpha.factors.llm_factor_generator import generate_factor_candidates_with_llm
from agent_alpha.memory.feedback_memory import append_feedback_record


class FakeFactorClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0
        self.messages: list[dict[str, str]] = []

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.calls += 1
        self.messages = messages
        return self.payload


class FakeMcpFactorClient(FakeFactorClient):
    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(payload)
        self.tool_names: list[str] = []
        self.tool_role = ""

    def complete_json_with_mcp_tools(self, messages: list[dict[str, Any]], *, tool_names: list[str], role: str, max_tool_rounds: int = 4) -> dict[str, Any]:
        self.calls += 1
        self.messages = messages
        self.tool_names = tool_names
        self.tool_role = role
        return self.payload


def _signal() -> dict[str, Any]:
    return {
        "signal_id": "sig_lob_imbalance",
        "source_reading_note_id": "note_lob",
        "signal_name": "LOB imbalance pressure",
        "expected_direction": "positive",
        "hf_mechanism_tags": ["order_book_pressure"],
    }


def _payload(prefix_expression: Any, *, expression: str = "") -> dict[str, Any]:
    return {
        "factor_candidates": [
            {
                "factor_id": "lob_imbalance_l1",
                "name": "lob_imbalance_l1",
                "prefix_expression": prefix_expression,
                "expression": expression,
                "fields": ["bidV1", "askV1"],
                "windows": [],
                "direction": "positive",
                "source_signal_id": "sig_lob_imbalance",
                "source_reading_note_id": "note_lob",
                "mechanism_tags": ["order_book_pressure"],
            }
        ]
    }


def test_generate_factor_candidates_accepts_prefix_json_and_derives_expression(tmp_path: Path) -> None:
    prefix = ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]]
    client = FakeFactorClient(_payload(prefix))

    candidates = generate_factor_candidates_with_llm(_signal(), client, max_candidates=1)

    assert client.calls == 1
    assert "Agent Alpha The Implementer" in client.messages[0]["content"]
    assert "Do not output Python code" in client.messages[0]["content"]
    assert "Mandatory format gate" in client.messages[0]["content"]
    assert '{ "factor_candidates": [] }' in client.messages[0]["content"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["prefix_expression"] == prefix
    assert candidate["expression"] == "safe_div((bidV1 - askV1), (bidV1 + askV1))"
    rendered = render_factor_file(candidate, tmp_path)
    py_compile.compile(str(rendered), doraise=True)


def test_generate_factor_candidates_uses_mcp_tools_when_available() -> None:
    prefix = ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]]
    client = FakeMcpFactorClient(_payload(prefix))

    candidates = generate_factor_candidates_with_llm(_signal(), client, max_candidates=1)

    assert len(candidates) == 1
    assert client.tool_role == "The Implementer"
    assert "market_data.list_fields" in client.tool_names
    assert "factor.render_and_compile_candidate" in client.tool_names


@pytest.mark.parametrize(
    "bad_text",
    [
        "def compute_factor(code, date, df): return df",
        "import pandas as pd",
        "import numpy as np",
        "lambda df: df",
        "```python\nprint('no')\n```",
    ],
)
def test_generate_factor_candidates_rejects_python_markers(bad_text: str) -> None:
    client = FakeFactorClient(_payload(["add", "bidV1", "askV1"], expression=bad_text))

    with pytest.raises(RuntimeError, match="must not contain Python code"):
        generate_factor_candidates_with_llm(_signal(), client, max_candidates=1)


def test_generate_factor_candidates_rejects_label_leakage() -> None:
    client = FakeFactorClient(
        {
            "factor_candidates": [
                {
                    "factor_id": "bad_label",
                    "name": "bad_label",
                    "prefix_expression": ["rolling_mean", "ret60s", 20],
                    "fields": ["ret60s"],
                    "windows": [20],
                }
            ]
        }
    )

    with pytest.raises(RuntimeError, match="forbidden fields|failed validation"):
        generate_factor_candidates_with_llm(_signal(), client, max_candidates=1)


def test_generate_factor_candidates_rejects_unknown_prefix_op() -> None:
    client = FakeFactorClient(_payload(["mystery_op", "bidV1"]))

    with pytest.raises(RuntimeError, match="failed validation"):
        generate_factor_candidates_with_llm(_signal(), client, max_candidates=1)


def test_generate_factor_candidates_filters_invalid_output_without_retry_when_not_strict() -> None:
    client = FakeFactorClient(_payload(["cond", "threshold_value", "bidV1", "null"]))

    assert generate_factor_candidates_with_llm(_signal(), client, max_candidates=1, strict=False) == []
    assert client.calls == 1


def test_generate_factor_candidates_injects_mechanism_prompts_and_good_bad_memory(tmp_path: Path) -> None:
    feedback_path = tmp_path / "feedback.jsonl"
    append_feedback_record(
        {
            "factor_id": "good_lob",
            "label": "GOOD",
            "reusable_principle": "Reuse order-book pressure with explicit spread normalization.",
        },
        path=feedback_path,
    )
    append_feedback_record(
        {
            "factor_id": "bad_lob",
            "label": "BAD",
            "avoid_rule": "Avoid raw depth subtraction without safe normalization.",
        },
        path=feedback_path,
    )
    append_feedback_record(
        {
            "factor_id": "revise_lob",
            "label": "REVISE",
            "repair_hint": "Try a longer normalization window.",
        },
        path=feedback_path,
    )
    prefix = ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]]
    client = FakeFactorClient(_payload(prefix))

    generate_factor_candidates_with_llm(_signal(), client, max_candidates=1, feedback_memory_path=feedback_path)

    prompt_payload = json.loads(client.messages[1]["content"])
    context = prompt_payload["prompt_context"]
    assert "factor_candidate_format_checker" in context
    assert "Allowed ASL Ops" in context["factor_candidate_format_checker"]
    assert "threshold_value" in context["factor_candidate_format_checker"]
    assert "supported_fields_and_asl" in context
    assert "Renderer Boundary" in context["supported_fields_and_asl"]
    assert "Safe Raw Fields" in context["supported_fields_and_asl"]
    assert "midP" in context["supported_fields_and_asl"]
    assert "Reuse order-book" in context["good_bad_memory"]["reuse_principles"][0]
    assert "Avoid raw depth" in context["good_bad_memory"]["avoid_rules"][0]
    assert "longer normalization" in context["good_bad_memory"]["repair_hints"][0]
    assert context["skill_rules"]
    assert context["shared_constraints"]
    assert "asl_factor_candidate_output.md" in context["shared_constraints"]
    assert "hf_output_format.md" not in context["shared_constraints"]
    assert context["mechanism_prompts"]
    assert "FactorCandidate" in context["mechanism_prompts"][0]["text"]
    assert "Do not write Python code" in context["mechanism_prompts"][0]["text"]
