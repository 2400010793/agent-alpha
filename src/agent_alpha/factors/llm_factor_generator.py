from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_alpha.factors.llm_candidate_guard import admit_factor_candidate_with_mcp
from agent_alpha.llm.client import LLMClient
from agent_alpha.llm.prompt_runner import load_prompt
from agent_alpha.rag.field_registry import FieldRegistry
from agent_alpha.skills.context_builder import build_prompt_context


_PYTHON_CODE_MARKERS = ("def ", "compute_factor", "```", "import pandas", "import numpy", "lambda")


def _contains_python_code(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return any(marker in lowered for marker in _PYTHON_CODE_MARKERS)
    if isinstance(value, dict):
        return any(_contains_python_code(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_python_code(item) for item in value)
    return False


def generate_factor_candidates_with_llm(
    signal: dict[str, Any],
    client: LLMClient,
    *,
    max_candidates: int = 2,
    feedback_memory_path: str | Path | None = None,
    strict: bool = True,
    use_mcp_tools: bool = True,
) -> list[dict[str, Any]]:
    """Use the LLM Implementer to produce FactorCandidate JSON, not Python code."""
    registry = FieldRegistry.from_yaml()
    mechanism_tags = [str(tag) for tag in signal.get("hf_mechanism_tags", []) if str(tag)]
    memory_query = " ".join(str(signal.get(key, "")) for key in ("signal_name", "market_intuition", "hypothesis"))
    prompt_context = build_prompt_context(
        task="signal_to_factor",
        skill_name="signal_to_factor",
        mechanism_tags=mechanism_tags,
        memory_query=memory_query,
        feedback_path=feedback_memory_path or "data/feedback_memory/good_bad.jsonl",
    )
    messages = [
        {
            "role": "system",
            "content": load_prompt("prompts/factor_expression/factor_candidate_asl_system.md"),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "signal": signal,
                    "max_candidates": max_candidates,
                    "allowed_input_fields": sorted(registry.allowed_input_fields),
                    "derived_feature_fields": sorted(registry.derived_feature_fields),
                    "label_fields_forbidden": sorted(registry.label_fields),
                    "prompt_context": prompt_context,
                    "required_candidate_schema": {
                        "factor_id": "stable id",
                        "name": "fac_eval output field name",
                        "prefix_expression": ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]],
                        "expression": "small DSL expression string derived from prefix_expression",
                        "fields": ["input or derived fields used by expression, labels excluded"],
                        "windows": ["integer windows used by expression"],
                        "direction": "positive|negative|conditional|unknown",
                        "source_signal_id": signal.get("signal_id", ""),
                        "source_reading_note_id": signal.get("source_reading_note_id", ""),
                        "mechanism_tags": signal.get("hf_mechanism_tags", []),
                    },
                    "output_format": {"factor_candidates": []},
                },
                ensure_ascii=False,
            ),
        },
    ]
    if use_mcp_tools and hasattr(client, "complete_json_with_mcp_tools"):
        payload = client.complete_json_with_mcp_tools(
            messages,
            tool_names=[
                "market_data.list_fields",
                "evaluation_memory.get_good_bad_memory",
                "function_memory.search",
                "factor.validate_candidate",
                "factor.render_and_compile_candidate",
            ],
            role="The Implementer",
        )
    else:
        payload = client.complete_json(messages)
    if _contains_python_code(payload):
        raise RuntimeError("LLM factor response must not contain Python code or compute_factor")
    raw_candidates = payload.get("factor_candidates", [])
    if not isinstance(raw_candidates, list):
        raise RuntimeError("LLM factor response must contain a list under key 'factor_candidates'")
    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(raw_candidates[:max_candidates], start=1):
        if not isinstance(item, dict):
            continue
        if not item.get("factor_id"):
            item["factor_id"] = f"{signal.get('signal_id', 'signal')}_factor_{index}"
        if not item.get("name"):
            item["name"] = item["factor_id"]
        item.setdefault("source_signal_id", signal.get("signal_id", ""))
        item.setdefault("source_reading_note_id", signal.get("source_reading_note_id", ""))
        item.setdefault("mechanism_tags", signal.get("hf_mechanism_tags", []))
        if item.get("prefix_expression") is None:
            if strict:
                raise RuntimeError("LLM factor response must include prefix_expression")
            continue
        qualification = admit_factor_candidate_with_mcp(item)
        if not qualification.ok:
            if strict:
                raise RuntimeError(f"LLM factor response failed validation: {qualification.message}")
            continue
        candidates.append(qualification.candidate or {})
    return candidates