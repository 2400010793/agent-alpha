from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_alpha.llm.client import LLMClient
from agent_alpha.llm.prompt_runner import load_prompt
from agent_alpha.rag.field_registry import FieldRegistry
from agent_alpha.signals.llm_signal_guard import allowed_candidate_fields, allowed_mechanism_tags, qualify_alpha_signal_payload
from agent_alpha.skills.context_builder import load_skill_rules


VALID_SIGNAL_MUTATION_TYPES = {
    "event_definition_mutation",
    "state_condition_mutation",
    "response_shape_mutation",
    "time_structure_mutation",
    "refinement_simplification",
}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def generate_signal_mutations(
    parent_signal: dict[str, Any],
    client: LLMClient,
    *,
    exploration_direction: str = "",
    max_mutations: int = 3,
) -> list[dict[str, Any]]:
    registry = FieldRegistry.from_yaml()
    allowed_tags = sorted(allowed_mechanism_tags())
    allowed_fields = sorted(allowed_candidate_fields(registry))
    messages = [
        {"role": "system", "content": load_prompt("prompts/thinking_evolution/signal_mutation_v1_system.md")},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "parent_signal": parent_signal,
                    "exploration_direction": exploration_direction,
                    "max_mutations": max_mutations,
                    "allowed_mutation_types": sorted(VALID_SIGNAL_MUTATION_TYPES),
                    "allowed_hf_mechanism_tags": allowed_tags,
                    "allowed_candidate_fields": allowed_fields,
                    "label_fields_forbidden": sorted(registry.label_fields),
                    "signal_format_checker": load_skill_rules("signal_format_checker"),
                },
                ensure_ascii=False,
            ),
        },
    ]
    payload = client.complete_json(messages)
    raw_mutations = _as_list(payload.get("signal_mutations"))[:max_mutations]
    mutations: list[dict[str, Any]] = []
    for index, mutation in enumerate(raw_mutations, start=1):
        if not isinstance(mutation, dict):
            continue
        mutation_type = str(mutation.get("mutation_type") or "")
        if mutation_type not in VALID_SIGNAL_MUTATION_TYPES:
            continue
        signal_payload = mutation.get("signal")
        if not isinstance(signal_payload, dict):
            continue
        qualification = qualify_alpha_signal_payload(signal_payload, parent_signal=parent_signal, registry=registry)
        if not qualification.ok:
            continue
        if not str(mutation.get("mutated_idea") or "").strip():
            continue
        signal = qualification.signal or {}
        mutations.append(
            {
                "mutation_id": str(mutation.get("mutation_id") or f"signal_mutation_{index}"),
                "mutation_type": mutation_type,
                "parent_signal_id": str(mutation.get("parent_signal_id") or parent_signal.get("signal_id") or ""),
                "parent_idea": str(mutation.get("parent_idea") or parent_signal.get("market_intuition") or ""),
                "mutated_idea": str(mutation.get("mutated_idea") or ""),
                "financial_reason": str(mutation.get("financial_reason") or ""),
                "expected_effect": str(mutation.get("expected_effect") or ""),
                "changed_components": [str(item) for item in _as_list(mutation.get("changed_components"))],
                "risk_note": str(mutation.get("risk_note") or ""),
                "signal": signal,
            }
        )
    return mutations


__all__ = ["VALID_SIGNAL_MUTATION_TYPES", "generate_signal_mutations"]