"""LLM JSON utilities independent of the old daily pipeline."""
from __future__ import annotations

import json
import re
from typing import Any, Dict


def extract_json_block(text: str) -> Dict[str, Any]:
	value = text.strip()
	if value.startswith("```"):
		value = re.sub(r"^```[a-zA-Z]*\n?", "", value)
		value = re.sub(r"\n?```$", "", value)
	start, end = value.find("{"), value.rfind("}")
	return json.loads(value[start:end + 1] if start >= 0 and end > start else value)


def balance_json_closers(text: str) -> str:
	stack, quoted, escaped = [], False, False
	for char in text:
		if quoted:
			if escaped: escaped = False
			elif char == "\\": escaped = True
			elif char == '"': quoted = False
		elif char == '"': quoted = True
		elif char == "{": stack.append("}")
		elif char == "[": stack.append("]")
		elif char in "}]" and stack and stack[-1] == char: stack.pop()
	return text + "".join(reversed(stack))


_extract_json_block = extract_json_block
_balance_json_closers = balance_json_closers
_validate_llm_analysis_payload = lambda *_args, **_kwargs: None

__all__ = ["extract_json_block", "balance_json_closers", "_extract_json_block", "_validate_llm_analysis_payload", "_balance_json_closers"]