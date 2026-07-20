from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_alpha.llm.client import LLMClient
from agent_alpha.llm.prompt_runner import load_prompt
from agent_alpha.rag.field_registry import FieldRegistry
from agent_alpha.skills.context_builder import build_prompt_context
from agent_alpha.signals.signal_ranker import rank_signals
from agent_alpha.signals.signal_schema import AlphaSignal, validate_alpha_signal
from agent_alpha.taxonomy.hf_taxonomy import load_hf_mechanisms


REQUIRED_SIGNAL_FIELDS = (
	"signal_id",
	"source_paper_id",
	"source_reading_note_id",
	"signal_name",
	"market_intuition",
	"hypothesis",
	"expected_direction",
	"hf_mechanism_tags",
	"candidate_fields",
	"evidence_ids",
)


def _allowed_mechanism_tags() -> set[str]:
	return {str(item.get("id")) for item in load_hf_mechanisms() if item.get("id")}


def _allowed_candidate_fields(registry: FieldRegistry) -> set[str]:
	return (registry.allowed_input_fields | registry.derived_feature_fields) - registry.label_fields - registry.blocked_fields


def _as_string_list(value: Any) -> list[str]:
	if not isinstance(value, list):
		return []
	return [str(item) for item in value]


def generate_signals_from_reading_note(
	reading_note: dict[str, Any],
	client: LLMClient | None = None,
	*,
	max_signals: int = 3,
	feedback_memory_path: str | Path | None = None,
) -> list[dict[str, Any]]:
	"""Generate AlphaSignal objects from a gated reading note with the LLM Idea Person."""
	if client is None:
		raise NotImplementedError("Idea Person LLM signal generation requires an LLMClient")
	registry = FieldRegistry.from_yaml()
	allowed_tags = sorted(_allowed_mechanism_tags())
	allowed_fields = sorted(_allowed_candidate_fields(registry))
	memory_query = " ".join(str(reading_note.get(key, "")) for key in ("paper_title", "main_mechanism", "research_question"))
	prompt_context = build_prompt_context(
		task="paper_to_signal",
		skill_name="paper_to_signal",
		memory_query=memory_query,
		feedback_path=feedback_memory_path or "data/feedback_memory/good_bad.jsonl",
	)
	messages = [
		{
			"role": "system",
			"content": load_prompt("prompts/signal_generation/alpha_signal_v1_system.md"),
		},
		{
			"role": "user",
			"content": json.dumps(
				{
					"reading_note": reading_note,
					"max_signals": max_signals,
					"allowed_hf_mechanism_tags": allowed_tags,
					"allowed_candidate_fields": allowed_fields,
					"label_fields_forbidden": sorted(registry.label_fields),
					"prompt_context": prompt_context,
					"required_signal_schema": {
						"signal_id": "short stable id",
						"source_paper_id": reading_note.get("paper_id", ""),
						"source_reading_note_id": reading_note.get("paper_id", ""),
						"signal_name": "specific HF signal name",
						"market_intuition": "why this signal may work",
						"hypothesis": "testable statement",
						"expected_direction": "positive|negative|conditional|unknown",
						"hf_mechanism_tags": allowed_tags,
						"candidate_fields": ["field names from field registry, labels excluded"],
						"evidence_ids": ["evidence ids or chunk ids"],
					},
					"output_format": {"signals": []},
				},
				ensure_ascii=False,
			),
		},
	]
	payload = client.complete_json(messages)
	signals = payload.get("signals", [])
	if not isinstance(signals, list):
		raise RuntimeError("LLM signal response must contain a list under key 'signals'")
	normalized: list[dict[str, Any]] = []
	for index, item in enumerate(signals[:max_signals], start=1):
		if not isinstance(item, dict):
			continue
		signal_id = str(item.get("signal_id") or f"signal_{index}")
		hf_mechanism_tags = [tag for tag in _as_string_list(item.get("hf_mechanism_tags")) if tag in allowed_tags]
		candidate_fields = [field for field in _as_string_list(item.get("candidate_fields")) if field in allowed_fields]
		signal = AlphaSignal.from_mapping(
			{
				"signal_id": signal_id,
				"source_paper_id": str(item.get("source_paper_id") or reading_note.get("paper_id") or ""),
				"source_reading_note_id": str(item.get("source_reading_note_id") or reading_note.get("paper_id") or ""),
				"signal_name": str(item.get("signal_name") or signal_id),
				"market_intuition": str(item.get("market_intuition") or ""),
				"hypothesis": str(item.get("hypothesis") or ""),
				"expected_direction": str(item.get("expected_direction") or "unknown"),
				"hf_mechanism_tags": hf_mechanism_tags,
				"candidate_fields": candidate_fields,
				"evidence_ids": _as_string_list(item.get("evidence_ids")),
			}
		)
		payload = signal.to_dict()
		validate_alpha_signal(payload)
		normalized.append(payload)
	return rank_signals(normalized)

__all__ = ["REQUIRED_SIGNAL_FIELDS", "generate_signals_from_reading_note"]