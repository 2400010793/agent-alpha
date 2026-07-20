from __future__ import annotations

from typing import Any

from agent_alpha.llm.client import LLMClient
from agent_alpha.reading.extractive_paper_reader import build_extractive_reading_note
from agent_alpha.reading.llm_paper_reader import build_llm_reading_note


def build_reading_note(
	chunks: list[Any],
	*,
	use_llm_reading: bool = False,
	client: LLMClient | None = None,
) -> dict[str, Any]:
	if use_llm_reading:
		if client is None:
			raise ValueError("client is required when use_llm_reading=True")
		return build_llm_reading_note(chunks, client)
	return build_extractive_reading_note(chunks)


__all__ = ["build_extractive_reading_note", "build_llm_reading_note", "build_reading_note"]