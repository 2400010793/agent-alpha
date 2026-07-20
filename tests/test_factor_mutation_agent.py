from __future__ import annotations

from typing import Any

import pytest

from agent_alpha.factors.expression_validator import validate_factor_candidate
from agent_alpha.memory.function_memory import load_function_memory
from agent_alpha.memory.memory_summary_agent import MemorySummaryAgent, MemorySummaryPaths
from agent_alpha.memory.specialist_memory import load_specialist_memory
from agent_alpha.memory.transfer_memory import load_transfer_memory
from agent_alpha.search.factor_mutation import generate_factor_mutations
from agent_alpha.search.mutation_guard import canonical_prefix, prefix_equivalent
from agent_alpha.search.iterative_enhancer import enhance_candidates
from agent_alpha.search.mutation_controller import select_mutation_plan


class FakeFactorMutationClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.messages: list[dict[str, str]] = []

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.messages = messages
        return self.payload


class FakeMcpFactorMutationClient(FakeFactorMutationClient):
    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(payload)
        self.tool_names: list[str] = []
        self.tool_role = ""

    def complete_json_with_mcp_tools(self, messages: list[dict[str, Any]], *, tool_names: list[str], role: str, max_tool_rounds: int = 4) -> dict[str, Any]:
        self.messages = messages
        self.tool_names = tool_names
        self.tool_role = role
        return self.payload


def _parent_candidate() -> dict[str, Any]:
    return {
        "factor_id": "volume_pressure",
        "name": "volume_pressure",
        "prefix_expression": ["zscore", "volume", 60],
        "expression": "zscore(volume, 60)",
        "fields": ["volume"],
        "windows": [60],
        "direction": "positive",
        "source_signal_id": "sig_volume",
        "source_reading_note_id": "note_volume",
        "mechanism_tags": ["trade_impact"],
        "economic_rationale": "Volume shock may indicate pressure.",
    }


def _mutation_payload(prefix_expression: Any | None = None) -> dict[str, Any]:
    prefix = prefix_expression or ["mul", ["zscore", "volume", 60], ["zscore", "close", 20]]
    return {
        "mutations": [
            {
                "mutation_id": "mut_volume_price_confirm",
                "mutation_type": "event_definition_mutation",
                "parent_factor_id": "volume_pressure",
                "parent_idea": "Volume shock may indicate pressure.",
                "mutated_idea": "Volume shock is only active when current price movement confirms the activity.",
                "financial_reason": "Activity without price confirmation may be absorption rather than directional pressure.",
                "expected_effect": "Reduce false positives from volume-only shocks.",
                "failure_mode_addressed": "volume_only_false_positive",
                "kept_core_mechanism": "activity shock pressure",
                "changed_components": ["event_definition", "price_confirmation"],
                "removed_components": [],
                "risk_note": "May miss absorbed but informed flow.",
                "factor_candidate": {
                    "factor_id": "volume_price_confirm_pressure",
                    "name": "volume_price_confirm_pressure",
                    "prefix_expression": prefix,
                    "expression": "",
                    "fields": ["volume", "close"],
                    "windows": [60, 20],
                    "direction": "positive",
                    "source_signal_id": "sig_volume",
                    "source_reading_note_id": "note_volume",
                    "mechanism_tags": ["trade_impact"],
                    "economic_rationale": "Volume shock is filtered by price confirmation.",
                },
            }
        ]
    }


def test_factor_mutation_agent_outputs_valid_factor_candidate() -> None:
    client = FakeFactorMutationClient(_mutation_payload())

    mutations = generate_factor_mutations(_parent_candidate(), client, exploration_direction="price confirmation")

    assert len(mutations) == 1
    child = mutations[0]
    assert child["created_by"] == "llm_factor_mutation_agent"
    assert child["mutation_type"] == "event_definition_mutation"
    assert child["parent_ids"] == ["volume_pressure"]
    assert "price confirms" in child["mutated_idea"] or "price movement confirms" in child["mutated_idea"]
    validation = validate_factor_candidate(child)
    assert validation.ok, validation.message
    assert "Factor Mutation Agent" in client.messages[0]["content"]
    prompt_payload = __import__("json").loads(client.messages[1]["content"])
    assert "Mandatory format gate" in prompt_payload["shared_factor_mutation_rules"]
    assert "simple sign reversal" in prompt_payload["shared_factor_mutation_rules"]
    assert "nonlinear or state-dependent" in prompt_payload["shared_factor_mutation_rules"]
    assert '{ "mutations": [] }' in prompt_payload["shared_factor_mutation_rules"]
    assert "factor_candidate_format_checker" in client.messages[1]["content"]
    assert "mutation_memory_skill" in client.messages[1]["content"]
    assert "function_memory" in prompt_payload["mutation_memory_skill"]
    assert "transfer_memory" in prompt_payload["mutation_memory_skill"]
    assert "Allowed ASL Ops" in client.messages[1]["content"]
    assert "supported_fields_and_asl" in client.messages[1]["content"]
    assert "Renderer Boundary" in client.messages[1]["content"]
    assert "Safe Raw Fields" in client.messages[1]["content"]


def test_factor_mutation_agent_uses_mcp_tools_when_available() -> None:
    client = FakeMcpFactorMutationClient(_mutation_payload())

    mutations = generate_factor_mutations(_parent_candidate(), client, exploration_direction="price confirmation")

    assert len(mutations) == 1
    assert client.tool_role == "The Implementer"
    assert "specialist_memory.search" in client.tool_names
    assert "function_memory.search" in client.tool_names
    assert "factor.render_and_compile_candidate" in client.tool_names


def test_factor_mutation_agent_coerces_numeric_string_literals() -> None:
    payload = _mutation_payload(["SafeDiv", "volume", ["mult", "close", "1"]])
    client = FakeFactorMutationClient(payload)

    mutations = generate_factor_mutations(_parent_candidate(), client)

    assert mutations[0]["prefix_expression"] == ["safe_div", "volume", ["mul", "close", 1]]
    assert mutations[0]["fields"] == ["volume", "close"]
    validation = validate_factor_candidate(mutations[0])
    assert validation.ok, validation.message


def test_factor_mutation_agent_rejects_cosmetic_zscore_only_mutation() -> None:
    payload = _mutation_payload(["zscore", "volume", 120])
    payload["mutations"][0]["parent_idea"] = "Volume shock may indicate pressure."
    payload["mutations"][0]["mutated_idea"] = "Volume shock may indicate pressure."
    payload["mutations"][0]["financial_reason"] = "stable"
    payload["mutations"][0]["changed_components"] = ["zscore", "window"]
    client = FakeFactorMutationClient(payload)

    assert generate_factor_mutations(_parent_candidate(), client) == []


def test_factor_mutation_agent_rejects_simple_parent_reversal() -> None:
    payload = _mutation_payload(["neg", ["zscore", "volume", 60]])
    payload["mutations"][0]["mutated_idea"] = "Flip the parent direction because metrics are negative."
    payload["mutations"][0]["financial_reason"] = "The sign was wrong."
    payload["mutations"][0]["changed_components"] = ["direction_flip"]
    client = FakeFactorMutationClient(payload)

    assert generate_factor_mutations(_parent_candidate(), client) == []


def test_canonical_prefix_removes_noop_transforms() -> None:
    assert canonical_prefix(["neg", ["neg", ["zscore", "volume", 60]]]) == ["zscore", "volume", 60]
    assert canonical_prefix(["mul", ["zscore", "volume", 60], 1]) == ["zscore", "volume", 60]
    assert canonical_prefix(["add", 0, ["zscore", "volume", 60]]) == ["zscore", "volume", 60]
    assert canonical_prefix(["safe_div", ["zscore", "volume", 60], 1]) == ["zscore", "volume", 60]
    assert prefix_equivalent(["sub", "bidV1", 0], "bidV1")


def test_factor_mutation_agent_rejects_equivalent_noop_mutation() -> None:
    payload = _mutation_payload(["mul", ["zscore", "volume", 60], 1])
    payload["mutations"][0]["mutated_idea"] = "Keep volume pressure and add a neutral multiplier."
    payload["mutations"][0]["financial_reason"] = "No actual change."
    payload["mutations"][0]["changed_components"] = ["neutral_multiplier"]
    client = FakeFactorMutationClient(payload)

    assert generate_factor_mutations(_parent_candidate(), client) == []


def test_factor_mutation_agent_drops_invalid_llm_output_without_retry() -> None:
    payload = _mutation_payload(["cond", "threshold_value", "volume", "null"])
    client = FakeFactorMutationClient(payload)

    assert generate_factor_mutations(_parent_candidate(), client) == []
    assert len(client.messages) == 2


def test_factor_mutation_agent_rejects_python_code() -> None:
    payload = _mutation_payload()
    payload["mutations"][0]["factor_candidate"]["expression"] = "def compute_factor(code, date, df): pass"
    client = FakeFactorMutationClient(payload)

    with pytest.raises(RuntimeError, match="must not contain Python code"):
        generate_factor_mutations(_parent_candidate(), client)


def test_iterative_enhancer_uses_llm_client_and_returns_empty_without_client() -> None:
    parent = _parent_candidate()
    feedback = [{"factor_id": "volume_pressure", "label": "BAD", "summary": "volume-only shocks are noisy"}]
    assert enhance_candidates([parent], feedback, max_new_candidates=3) == []

    client = FakeFactorMutationClient(_mutation_payload())
    enhanced = enhance_candidates([parent], feedback, max_new_candidates=3, client=client, exploration_direction="price confirmation")

    assert len(enhanced) == 1
    assert enhanced[0]["created_by"] == "llm_factor_mutation_agent"
    assert "EventDefinitionMutationAgent" in client.messages[0]["content"]


def test_mutation_controller_selects_one_parent_and_specialist_focus() -> None:
    parent = _parent_candidate()
    weaker = {**_parent_candidate(), "factor_id": "weak_volume", "name": "weak_volume", "mutation_attempt": 5}
    feedback = [
        {"factor_id": "volume_pressure", "label": "BAD", "summary": "volume-only shocks are noisy", "metrics": {"daily_rankic": 0.05}},
        {"factor_id": "weak_volume", "label": "BAD", "summary": "weak", "metrics": {"daily_rankic": 0.01}},
    ]

    plan = select_mutation_plan([weaker, parent], feedback)

    assert plan is not None
    assert plan.parent_candidate["factor_id"] == "volume_pressure"
    assert plan.mutation_focus == "event_definition_mutation"
    assert plan.agent_name == "EventDefinitionMutationAgent"
    assert plan.memory_context["selector"]["arm_id"] == "volume_pressure:event_definition_mutation"


def test_mutation_controller_combines_parent_and_agent_with_arm_memory() -> None:
    parent = {**_parent_candidate(), "lineage_id": "volume_lineage"}
    feedback = [{"factor_id": "volume_pressure", "label": "BAD", "summary": "volume-only shocks are noisy", "metrics": {"daily_rankic": 0.05}}]
    arm_memory = {
        "volume_lineage:state_condition_mutation": {"n_trials": 4, "mean_reward": 0.3, "failure_count": 0},
        "volume_lineage:event_definition_mutation": {"n_trials": 4, "mean_reward": -0.02, "failure_count": 2},
    }

    plan = select_mutation_plan([parent], feedback, arm_memory=arm_memory, exploration_c=0.0)

    assert plan is not None
    assert plan.mutation_focus == "state_condition_mutation"
    assert plan.agent_name == "StateConditionMutationAgent"
    assert plan.memory_context["selector"]["arm_stats"]["mean_reward"] == 0.3


def test_mutation_controller_skips_stopped_lineage_and_prefers_near_elite() -> None:
    stopped = {**_parent_candidate(), "factor_id": "stopped_parent", "name": "stopped_parent", "lineage_id": "dead_lineage"}
    near = {**_parent_candidate(), "factor_id": "near_parent", "name": "near_parent", "lineage_id": "live_lineage"}
    weak = {**_parent_candidate(), "factor_id": "weak_parent", "name": "weak_parent", "lineage_id": "weak_lineage"}
    feedback = [
        {"factor_id": "stopped_parent", "label": "BAD", "summary": "strong but stopped", "metrics": {"daily_rankic": 0.079}},
        {"factor_id": "near_parent", "label": "REVISE", "summary": "near elite", "metrics": {"daily_rankic": 0.072}},
        {"factor_id": "weak_parent", "label": "REVISE", "summary": "weak", "metrics": {"daily_rankic": 0.02}},
    ]

    plan = select_mutation_plan([stopped, weak, near], feedback, lineage_states={"dead_lineage": {"stopped": True}})

    assert plan is not None
    assert plan.parent_candidate["factor_id"] == "near_parent"


def test_iterative_enhancer_uses_one_specialist_and_writes_memory(tmp_path, monkeypatch) -> None:
    import agent_alpha.memory.specialist_memory as specialist_memory
    import agent_alpha.search.iterative_enhancer as iterative_enhancer
    import agent_alpha.search.memory_summarizer as memory_summarizer

    monkeypatch.setattr(specialist_memory, "DEFAULT_SPECIALIST_MEMORY_DIR", str(tmp_path / "specialists"))
    monkeypatch.setattr(iterative_enhancer, "search_specialist_memory", lambda agent_name, query='', limit=5: [])

    def write_memory(plan, children):
        records = []
        for child in children:
            records.append(specialist_memory.append_specialist_memory(plan.agent_name, memory_summarizer.summarize_mutation_proposal(plan, child), root=tmp_path / "specialists"))
        return records

    monkeypatch.setattr(iterative_enhancer, "write_specialist_mutation_memory", write_memory)
    client = FakeFactorMutationClient(_mutation_payload())

    enhanced = enhance_candidates([_parent_candidate()], [{"factor_id": "volume_pressure", "label": "BAD", "summary": "volume-only shocks are noisy"}], max_new_candidates=3, client=client)

    assert len(enhanced) == 1
    assert enhanced[0]["specialist_agent_name"] == "EventDefinitionMutationAgent"
    stored = load_specialist_memory("EventDefinitionMutationAgent", root=tmp_path / "specialists")
    assert stored[0]["child_factor_id"] == "volume_price_confirm_pressure"


def test_iterative_enhancer_passes_lineage_context_to_specialist(monkeypatch) -> None:
    import json
    import agent_alpha.search.iterative_enhancer as iterative_enhancer

    monkeypatch.setattr(iterative_enhancer, "search_specialist_memory", lambda agent_name, query='', limit=5: [])
    parent = _parent_candidate()
    child_parent = {
        **_parent_candidate(),
        "factor_id": "volume_pressure_child",
        "name": "volume_pressure_child",
        "parent_ids": ["volume_pressure"],
        "prefix_expression": ["mul", ["zscore", "volume", 60], ["zscore", "close", 20]],
        "fields": ["volume", "close"],
    }
    feedback = [
        {"factor_id": "volume_pressure", "label": "BAD", "summary": "volume-only shocks are noisy", "metrics": {"daily_rankic": 0.03}},
        {"factor_id": "volume_pressure_child", "label": "BAD", "summary": "volume-only shocks are noisy", "metrics": {"daily_rankic": 0.05}},
    ]
    client = FakeFactorMutationClient(_mutation_payload())

    enhance_candidates([parent, child_parent], feedback, max_new_candidates=1, client=client)

    prompt_payload = json.loads(client.messages[1]["content"])
    assert "lineage_context" not in prompt_payload
    assert "specialist_memory" not in prompt_payload
    lineage = prompt_payload["memory_context"]["lineage_context"]
    assert lineage["parent_factor_id"] == "volume_pressure_child"
    assert lineage["ancestor_count"] == 1
    assert [item["factor_id"] for item in lineage["chain"]] == ["volume_pressure", "volume_pressure_child"]
    assert lineage["chain"][1]["delta_from_previous"] == 0.020000000000000004


def test_iterative_enhancer_passes_bounded_memory_context_to_specialist(tmp_path, monkeypatch) -> None:
    import json
    import agent_alpha.search.iterative_enhancer as iterative_enhancer

    monkeypatch.setattr(iterative_enhancer, "search_specialist_memory", lambda agent_name, query='', limit=20: [{"summary": "specialist spread memory", "fields": ["spread_l1"]}])
    monkeypatch.setattr(iterative_enhancer, "search_function_memory", lambda query='', limit=20: [{"summary": "function zscore memory", "asl_ops": ["zscore"], "fields": ["volume"]}])
    monkeypatch.setattr(iterative_enhancer, "search_transfer_memory", lambda query='', limit=20: [{"summary": "transfer state memory", "mutation_type": "state_condition_mutation"}])
    client = FakeFactorMutationClient(_mutation_payload())

    enhance_candidates([_parent_candidate()], [{"factor_id": "volume_pressure", "label": "BAD", "summary": "volume-only shocks are noisy"}], client=client)

    prompt_payload = json.loads(client.messages[1]["content"])
    context = prompt_payload["memory_context"]
    assert context["budget"]["approx_max_tokens"] == 8000
    assert context["budget"]["actual_chars"] <= context["budget"]["max_chars"]
    assert context["specialist_memory"][0]["summary"] == "specialist spread memory"
    assert context["function_memory"][0]["summary"] == "function zscore memory"
    assert context["transfer_memory"][0]["summary"] == "transfer state memory"


def test_memory_summary_agent_writes_specialist_function_and_transfer_memory(tmp_path) -> None:
    plan = select_mutation_plan([_parent_candidate()], [{"factor_id": "volume_pressure", "label": "BAD", "summary": "volume-only shocks are noisy"}])
    child = {
        **_parent_candidate(),
        "factor_id": "volume_price_confirm_pressure",
        "name": "volume_price_confirm_pressure",
        "prefix_expression": ["mul", ["zscore", "volume", 60], ["zscore", "close", 20]],
        "fields": ["volume", "close"],
        "windows": [60, 20],
        "mutated_idea": "Volume pressure requires price confirmation.",
    }
    agent = MemorySummaryAgent(
        MemorySummaryPaths(
            specialist_root=tmp_path / "specialists",
            function_memory_path=tmp_path / "function_memory.jsonl",
            transfer_memory_path=tmp_path / "transfer_memory.jsonl",
        )
    )

    records = agent.write_mutation_memories(plan, child, child_review={"decision": "revise", "metrics": {"daily_rankic": 0.04}})

    assert records["specialist"]["agent_name"] == "EventDefinitionMutationAgent"
    assert load_specialist_memory("EventDefinitionMutationAgent", root=tmp_path / "specialists")[0]["child_factor_id"] == "volume_price_confirm_pressure"
    assert load_function_memory(tmp_path / "function_memory.jsonl")[0]["asl_ops"] == ["mul", "zscore"]
    assert load_transfer_memory(tmp_path / "transfer_memory.jsonl")[0]["mutation_type"] == "event_definition_mutation"