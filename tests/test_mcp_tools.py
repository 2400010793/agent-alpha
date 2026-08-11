from __future__ import annotations

from pathlib import Path

import pytest

from agent_alpha.mcp_tools.permission_guard import allowed_tools_for_role
from agent_alpha.mcp_tools.tool_specs import mcp_tool_spec
from agent_alpha.mcp_tools.tool_router import call_tool
from agent_alpha.memory.function_memory import append_function_memory
from agent_alpha.memory.specialist_memory import append_specialist_memory
from agent_alpha.memory.transfer_memory import append_transfer_memory


def _candidate(factor_id: str) -> dict:
    return {
        "factor_id": factor_id,
        "name": factor_id,
        "prefix_expression": ["zscore", "volume", 60],
        "fields": ["volume"],
        "windows": [60],
        "mechanism_tags": ["trade_impact"],
    }


def test_permission_guard_includes_specialist_memory_and_controller_tools() -> None:
    implementer_tools = allowed_tools_for_role("The Implementer")

    assert "market_data.recommend_fields" in implementer_tools
    assert "factor.validate_candidate" in implementer_tools
    assert "factor.render_and_compile_candidate" in implementer_tools
    assert "factor_registry.search_similar_factors" in implementer_tools
    assert "specialist_memory.search" in implementer_tools
    assert "function_memory.search" in implementer_tools
    assert "transfer_memory.search" in implementer_tools
    assert "mutation_controller.select_plan" in implementer_tools
    assert "mutation_controller.select_plan" not in allowed_tools_for_role("The Evaluator")


def test_mcp_tool_specs_include_precise_memory_parameters() -> None:
    recommend = mcp_tool_spec("market_data.recommend_fields")["function"]
    specialist = mcp_tool_spec("specialist_memory.search")["function"]
    function_memory = mcp_tool_spec("function_memory.search")["function"]
    similar = mcp_tool_spec("factor_registry.search_similar_factors")["function"]
    controller = mcp_tool_spec("mutation_controller.select_plan")["function"]

    assert recommend["parameters"]["required"] == ["signal"]
    assert "specialist mutation agent" in specialist["description"]
    assert specialist["parameters"]["required"] == ["agent_name"]
    assert "query" in function_memory["parameters"]["properties"]
    assert similar["parameters"]["required"] == ["signal"]
    assert controller["parameters"]["required"] == ["candidates"]


def test_field_recommendation_and_similar_factor_tools_return_envelopes(tmp_path: Path) -> None:
    signal = {
        "signal_id": "depth_hidden_liquidity",
        "signal_name": "Depth and hidden liquidity pressure",
        "hf_mechanism_tags": ["order_book_pressure", "hidden_liquidity"],
        "candidate_fields": ["depth_imbalance_l1", "totalDeputeBuy", "ret60s"],
    }
    source = tmp_path / "candidates.json"
    source.write_text('{"factor_candidates":[{"factor_id":"depth_alpha","fields":["depth_imbalance_l1"],"mechanism_tags":["order_book_pressure"]}]}', encoding="utf-8")

    fields = call_tool("market_data.recommend_fields", {"signal": signal, "limit": 5}, role="The Implementer")
    similar = call_tool("factor_registry.search_similar_factors", {"signal": signal, "candidate_sources": [str(source)], "limit": 2}, role="The Implementer")

    assert "ret60s" not in fields["results"]["recommended_field_names"]
    assert "depth_imbalance_l1" in fields["results"]["recommended_field_names"]
    assert similar["results"]["similar_factors"][0]["factor_id"] == "depth_alpha"


def test_specialist_memory_search_tool_returns_envelope(tmp_path: Path) -> None:
    append_specialist_memory(
        "StateConditionMutationAgent",
        {
            "mutation_focus": "state_condition_mutation",
            "label": "GOOD",
            "summary": "Spread stress helped filter raw book pressure.",
            "fields": ["spread_l1"],
        },
        root=tmp_path,
    )

    envelope = call_tool(
        "specialist_memory.search",
        {"agent_name": "StateConditionMutationAgent", "query": "spread", "root": str(tmp_path), "limit": 3},
        role="The Implementer",
    )

    assert envelope["tool_name"] == "specialist_memory.search"
    assert envelope["schema_version"] == "tool_envelope_v1"
    assert envelope["results"]["agent_name"] == "StateConditionMutationAgent"
    assert envelope["results"]["records"][0]["summary"].startswith("Spread stress")


def test_function_and_transfer_memory_search_tools_return_envelopes(tmp_path: Path) -> None:
    function_path = tmp_path / "function_memory.jsonl"
    transfer_path = tmp_path / "transfer_memory.jsonl"
    append_function_memory({"label": "BAD", "fields": ["volume"], "summary": "Raw volume zscore needs price confirmation."}, path=function_path)
    append_transfer_memory({"label": "GOOD", "mutation_type": "state_condition_mutation", "summary": "Spread state improved book pressure."}, path=transfer_path)

    function_envelope = call_tool("function_memory.search", {"query": "price", "path": str(function_path)}, role="The Implementer")
    transfer_envelope = call_tool("transfer_memory.search", {"query": "spread", "path": str(transfer_path)}, role="The Evaluator")

    assert function_envelope["results"]["records"][0]["fields"] == ["volume"]
    assert transfer_envelope["results"]["records"][0]["mutation_type"] == "state_condition_mutation"


def test_mutation_controller_select_plan_tool_returns_one_specialist() -> None:
    envelope = call_tool(
        "mutation_controller.select_plan",
        {
            "candidates": [_candidate("weak_volume"), _candidate("volume_pressure")],
            "feedback_records": [
                {
                    "factor_id": "volume_pressure",
                    "label": "BAD",
                    "summary": "volume-only shocks are noisy",
                    "metrics": {"daily_rankic": 0.05},
                }
            ],
        },
        role="The Implementer",
    )

    plan = envelope["results"]["plan"]
    assert plan["parent_factor_id"] == "volume_pressure"
    assert plan["mutation_focus"] == "event_definition_mutation"
    assert plan["agent_name"] == "EventDefinitionMutationAgent"
    assert plan["feedback_count"] == 1
    assert plan["memory_context"]["selector"]["arm_id"] == "volume_pressure:event_definition_mutation"


def test_mutation_controller_select_plan_tool_respects_stopped_lineage() -> None:
    stopped = {**_candidate("stopped_parent"), "lineage_id": "dead_lineage"}
    live = {**_candidate("live_parent"), "lineage_id": "live_lineage"}
    envelope = call_tool(
        "mutation_controller.select_plan",
        {
            "candidates": [stopped, live],
            "feedback_records": [
                {"factor_id": "stopped_parent", "label": "BAD", "metrics": {"daily_rankic": 0.079}},
                {"factor_id": "live_parent", "label": "REVISE", "metrics": {"daily_rankic": 0.04}},
            ],
            "lineage_states": {"dead_lineage": {"stopped": True}},
        },
        role="The Implementer",
    )

    assert envelope["results"]["plan"]["parent_factor_id"] == "live_parent"


def test_mutation_controller_tool_denies_evaluator_role() -> None:
    with pytest.raises(PermissionError):
        call_tool("mutation_controller.select_plan", {"candidates": []}, role="The Evaluator")


def test_factor_validate_candidate_tool_returns_canonical_candidate() -> None:
    envelope = call_tool(
        "factor.validate_candidate",
        {"candidate": {**_candidate("volume_pressure"), "prefix_expression": ["SafeDiv", "volume", "1"]}},
        role="The Implementer",
    )

    assert envelope["results"]["ok"] is True
    assert envelope["results"]["candidate"]["prefix_expression"] == ["safe_div", "volume", 1]
    assert envelope["results"]["candidate"]["fields"] == ["volume"]


def test_factor_render_and_compile_candidate_tool_accepts_good_and_rejects_bad(tmp_path: Path) -> None:
    good = call_tool(
        "factor.render_and_compile_candidate",
        {"candidate": _candidate("volume_pressure"), "output_dir": str(tmp_path)},
        role="The Implementer",
    )
    bad = call_tool(
        "factor.render_and_compile_candidate",
        {"candidate": {**_candidate("bad"), "prefix_expression": ["cond", "threshold_value", "volume", "null"]}},
        role="The Implementer",
    )

    assert good["results"]["ok"] is True
    assert Path(good["results"]["factor_file"]).exists()
    assert bad["results"]["ok"] is False
    assert bad["results"]["stage"] == "validate"
