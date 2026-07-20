from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_alpha.factors.llm_candidate_guard import admit_factor_candidate_with_mcp
from agent_alpha.llm.client import LLMClient
from agent_alpha.llm.prompt_runner import load_prompt
from agent_alpha.rag.field_registry import FieldRegistry
from agent_alpha.search.mutation_guard import is_empty_or_equivalent_mutation
from agent_alpha.search.mutation_controller import MUTATION_AGENT_BY_FOCUS
from agent_alpha.skills.context_builder import load_skill_rules


VALID_FACTOR_MUTATION_TYPES = {
    "event_definition_mutation",
    "state_condition_mutation",
    "response_shape_mutation",
    "normalization_robustness_mutation",
    "time_structure_mutation",
    "refinement_simplification",
}

PROMPT_BY_MUTATION_FOCUS = {
    "event_definition_mutation": "prompts/thinking_evolution/factor_mutation_event_definition_v1_system.md",
    "state_condition_mutation": "prompts/thinking_evolution/factor_mutation_state_condition_v1_system.md",
    "response_shape_mutation": "prompts/thinking_evolution/factor_mutation_response_shape_v1_system.md",
    "normalization_robustness_mutation": "prompts/thinking_evolution/factor_mutation_normalization_robustness_v1_system.md",
    "time_structure_mutation": "prompts/thinking_evolution/factor_mutation_time_structure_v1_system.md",
    "refinement_simplification": "prompts/thinking_evolution/factor_mutation_refinement_simplification_v1_system.md",
}

COSMETIC_COMPONENTS = {"zscore", "rank", "rolling_mean", "rolling_std", "rolling_sum", "normalization", "window"}
PYTHON_MARKERS = ("def ", "compute_factor", "```", "import pandas", "import numpy", "lambda")


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _contains_python(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return any(marker in lowered for marker in PYTHON_MARKERS)
    if isinstance(value, list):
        return any(_contains_python(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_python(item) for item in value.values())
    return False


def _is_cosmetic_mutation(parent_idea: str, mutated_idea: str, financial_reason: str, changed_components: list[str]) -> bool:
    parent_norm = " ".join(parent_idea.casefold().split())
    mutated_norm = " ".join(mutated_idea.casefold().split())
    component_set = {component.casefold() for component in changed_components}
    return bool(parent_norm and parent_norm == mutated_norm and component_set and component_set <= COSMETIC_COMPONENTS and len(financial_reason.strip()) < 30)


def _same_prefix(left: Any, right: Any) -> bool:
    return left == right


def _is_simple_reversal(parent_candidate: dict[str, Any], child_candidate: dict[str, Any]) -> bool:
    parent_prefix = parent_candidate.get("prefix_expression")
    child_prefix = child_candidate.get("prefix_expression")
    if parent_prefix is None or child_prefix is None:
        return False
    if isinstance(child_prefix, list) and len(child_prefix) == 2 and child_prefix[0] == "neg":
        return _same_prefix(child_prefix[1], parent_prefix)
    if isinstance(child_prefix, list) and len(child_prefix) == 3 and child_prefix[0] == "mul":
        left, right = child_prefix[1], child_prefix[2]
        return (left == -1 and _same_prefix(right, parent_prefix)) or (right == -1 and _same_prefix(left, parent_prefix))
    return False


def generate_factor_mutations(
    parent_candidate: dict[str, Any],
    client: LLMClient,
    *,
    parent_logic: str = "",
    evaluation_metrics: dict[str, Any] | None = None,
    effective_summary: str = "",
    ineffective_summary: str = "",
    exploration_direction: str = "",
    mutation_focus: str | None = None,
    agent_name: str | None = None,
    specialist_memory: list[dict[str, Any]] | None = None,
    lineage_context: dict[str, Any] | None = None,
    memory_context: dict[str, Any] | None = None,
    max_mutations: int = 3,
    use_mcp_tools: bool = True,
) -> list[dict[str, Any]]:
    registry = FieldRegistry.from_yaml()
    allowed_mutation_types = [mutation_focus] if mutation_focus in VALID_FACTOR_MUTATION_TYPES else sorted(VALID_FACTOR_MUTATION_TYPES)
    resolved_agent_name = agent_name or (MUTATION_AGENT_BY_FOCUS.get(mutation_focus or "") if mutation_focus else "FactorMutationAgent") or "FactorMutationAgent"
    shared_system_prompt = load_prompt("prompts/thinking_evolution/factor_mutation_v1_system.md")
    system_prompt = load_prompt(PROMPT_BY_MUTATION_FOCUS.get(mutation_focus or "", "prompts/thinking_evolution/factor_mutation_v1_system.md"))
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "parent_candidate": parent_candidate,
                    "parent_logic": parent_logic or parent_candidate.get("economic_rationale", ""),
                    "evaluation_metrics": evaluation_metrics or {},
                    "effective_summary": effective_summary,
                    "ineffective_summary": ineffective_summary,
                    "exploration_direction": exploration_direction,
                    "mutation_focus": mutation_focus or "",
                    "specialist_agent_name": resolved_agent_name,
                    "memory_context": memory_context or {"specialist_memory": specialist_memory or [], "lineage_context": lineage_context or {}},
                    "shared_factor_mutation_rules": shared_system_prompt,
                    "max_mutations": max_mutations,
                    "allowed_mutation_types": allowed_mutation_types,
                    "allowed_input_fields": sorted(registry.allowed_input_fields),
                    "derived_feature_fields": sorted(registry.derived_feature_fields),
                    "label_fields_forbidden": sorted(registry.label_fields),
                    "blocked_fields_forbidden": sorted(registry.blocked_fields),
                    "factor_candidate_format_checker": load_skill_rules("factor_candidate_format_checker"),
                    "supported_fields_and_asl": load_skill_rules("supported_fields_and_asl"),
                    "mutation_memory_skill": load_skill_rules("mutation_memory"),
                },
                ensure_ascii=False,
            ),
        },
    ]
    if use_mcp_tools and hasattr(client, "complete_json_with_mcp_tools"):
        payload = client.complete_json_with_mcp_tools(
            messages,
            tool_names=[
                "specialist_memory.search",
                "function_memory.search",
                "transfer_memory.search",
                "factor.validate_candidate",
                "factor.render_and_compile_candidate",
            ],
            role="The Implementer",
        )
    else:
        payload = client.complete_json(messages)
    if _contains_python(payload):
        raise RuntimeError("LLM factor mutation response must not contain Python code or compute_factor")
    raw_mutations = _as_list(payload.get("mutations"))[:max_mutations]
    mutations: list[dict[str, Any]] = []
    for index, mutation in enumerate(raw_mutations, start=1):
        if not isinstance(mutation, dict):
            continue
        mutation_type = str(mutation.get("mutation_type") or "")
        if mutation_type not in allowed_mutation_types:
            continue
        factor_payload = mutation.get("factor_candidate")
        if not isinstance(factor_payload, dict):
            continue
        parent_id = str(parent_candidate.get("factor_id") or parent_candidate.get("name") or "")
        factor_payload.setdefault("source_signal_id", parent_candidate.get("source_signal_id", ""))
        factor_payload.setdefault("source_reading_note_id", parent_candidate.get("source_reading_note_id", ""))
        factor_payload.setdefault("mechanism_tags", parent_candidate.get("mechanism_tags", []))
        qualification = admit_factor_candidate_with_mcp(factor_payload)
        if not qualification.ok:
            continue
        parent_idea = str(mutation.get("parent_idea") or parent_logic or parent_candidate.get("economic_rationale") or "")
        mutated_idea = str(mutation.get("mutated_idea") or "")
        financial_reason = str(mutation.get("financial_reason") or "")
        changed_components = [str(item) for item in _as_list(mutation.get("changed_components"))]
        if not mutated_idea.strip():
            continue
        if _is_cosmetic_mutation(parent_idea, mutated_idea, financial_reason, changed_components):
            continue
        candidate_dict = dict(qualification.candidate or {})
        if _is_simple_reversal(parent_candidate, candidate_dict) or is_empty_or_equivalent_mutation(parent_candidate, candidate_dict):
            continue
        candidate_dict.update(
            {
                "parent_ids": [parent_id] if parent_id else [],
                "created_by": "llm_factor_mutation_agent",
                "specialist_agent_name": resolved_agent_name,
                "mutation_id": str(mutation.get("mutation_id") or f"factor_mutation_{index}"),
                "mutation_type": mutation_type,
                "parent_idea": parent_idea,
                "mutated_idea": mutated_idea,
                "financial_reason": financial_reason,
                "expected_effect": str(mutation.get("expected_effect") or ""),
                "failure_mode_addressed": str(mutation.get("failure_mode_addressed") or ""),
                "kept_core_mechanism": str(mutation.get("kept_core_mechanism") or ""),
                "changed_components": changed_components,
                "removed_components": [str(item) for item in _as_list(mutation.get("removed_components"))],
                "risk_note": str(mutation.get("risk_note") or ""),
            }
        )
        mutations.append(candidate_dict)
    return mutations


__all__ = ["PROMPT_BY_MUTATION_FOCUS", "VALID_FACTOR_MUTATION_TYPES", "generate_factor_mutations"]