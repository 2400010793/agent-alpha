from __future__ import annotations

import json
from typing import Any

from agent_alpha.factors.llm_candidate_guard import qualify_factor_candidate_payload
from agent_alpha.llm.client import LLMClient
from agent_alpha.llm.prompt_runner import load_prompt
from agent_alpha.rag.field_registry import FieldRegistry
from agent_alpha.search.factor_mutation import PYTHON_MARKERS, _contains_python
from agent_alpha.skills.context_builder import load_skill_rules


VALID_FACTOR_CROSSOVER_TYPES = {
    "mechanism_crossover",
    "state_condition_crossover",
    "confirmation_crossover",
    "normalization_crossover",
    "time_structure_crossover",
    "simplified_hybrid",
}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _factor_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("factor_id") or candidate.get("name") or "")


def _parent_ids(parent_a: dict[str, Any], parent_b: dict[str, Any]) -> list[str]:
    return [factor_id for factor_id in [_factor_id(parent_a), _factor_id(parent_b)] if factor_id]


def generate_factor_crossovers(
    parent_a: dict[str, Any],
    parent_b: dict[str, Any],
    client: LLMClient,
    *,
    parent_a_review: dict[str, Any] | None = None,
    parent_b_review: dict[str, Any] | None = None,
    exploration_direction: str = "",
    max_crossovers: int = 3,
) -> list[dict[str, Any]]:
    registry = FieldRegistry.from_yaml()
    messages = [
        {"role": "system", "content": load_prompt("prompts/thinking_evolution/factor_crossover_v1_system.md")},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "parent_a": parent_a,
                    "parent_b": parent_b,
                    "parent_a_review": parent_a_review or {},
                    "parent_b_review": parent_b_review or {},
                    "exploration_direction": exploration_direction,
                    "max_crossovers": max_crossovers,
                    "allowed_crossover_types": sorted(VALID_FACTOR_CROSSOVER_TYPES),
                    "allowed_input_fields": sorted(registry.allowed_input_fields),
                    "derived_feature_fields": sorted(registry.derived_feature_fields),
                    "label_fields_forbidden": sorted(registry.label_fields),
                    "blocked_fields_forbidden": sorted(registry.blocked_fields),
                    "factor_candidate_format_checker": load_skill_rules("factor_candidate_format_checker"),
                    "supported_fields_and_asl": load_skill_rules("supported_fields_and_asl"),
                },
                ensure_ascii=False,
            ),
        },
    ]
    payload = client.complete_json(messages)
    if _contains_python(payload):
        raise RuntimeError("LLM factor crossover response must not contain Python code or compute_factor")
    raw_crossovers = _as_list(payload.get("crossovers"))[:max_crossovers]
    crossovers: list[dict[str, Any]] = []
    parents = _parent_ids(parent_a, parent_b)
    for index, crossover in enumerate(raw_crossovers, start=1):
        if not isinstance(crossover, dict):
            continue
        crossover_type = str(crossover.get("crossover_type") or "")
        if crossover_type not in VALID_FACTOR_CROSSOVER_TYPES:
            continue
        factor_payload = crossover.get("factor_candidate")
        if not isinstance(factor_payload, dict):
            continue
        factor_payload.setdefault("source_signal_id", parent_a.get("source_signal_id") or parent_b.get("source_signal_id") or "")
        factor_payload.setdefault("source_reading_note_id", parent_a.get("source_reading_note_id") or parent_b.get("source_reading_note_id") or "")
        factor_payload.setdefault("mechanism_tags", list(dict.fromkeys([*parent_a.get("mechanism_tags", []), *parent_b.get("mechanism_tags", [])])))
        qualification = qualify_factor_candidate_payload(factor_payload, registry=registry)
        if not qualification.ok:
            continue
        crossed_idea = str(crossover.get("crossed_idea") or crossover.get("mutated_idea") or "")
        financial_reason = str(crossover.get("financial_reason") or "")
        if not crossed_idea.strip() or not financial_reason.strip():
            continue
        candidate_dict = dict(qualification.candidate or {})
        candidate_dict.update(
            {
                "parent_ids": parents,
                "created_by": "llm_factor_crossover_agent",
                "crossover_id": str(crossover.get("crossover_id") or f"factor_crossover_{index}"),
                "crossover_type": crossover_type,
                "crossed_idea": crossed_idea,
                "financial_reason": financial_reason,
                "expected_effect": str(crossover.get("expected_effect") or ""),
                "combined_components": [str(item) for item in _as_list(crossover.get("combined_components"))],
                "kept_from_parent_a": [str(item) for item in _as_list(crossover.get("kept_from_parent_a"))],
                "kept_from_parent_b": [str(item) for item in _as_list(crossover.get("kept_from_parent_b"))],
                "removed_components": [str(item) for item in _as_list(crossover.get("removed_components"))],
                "risk_note": str(crossover.get("risk_note") or ""),
            }
        )
        crossovers.append(candidate_dict)
    return crossovers


__all__ = ["PYTHON_MARKERS", "VALID_FACTOR_CROSSOVER_TYPES", "generate_factor_crossovers"]