"""Stable evidence-pack interface for the Paper Opinion Digest."""
from __future__ import annotations

import re
from typing import Any, Dict, List


def _text(value: Any, limit: int = 1600) -> str:
	return " ".join(str(value or "").split())[:limit]


def _list(value: Any, limit: int = 8, text_limit: int = 1200) -> List[Any]:
	values = value if isinstance(value, list) else ([value] if value else [])
	return [_text(item, text_limit) if not isinstance(item, dict) else item for item in values[:limit]]


def _anchor(pack: Dict[str, Any]) -> Dict[str, str]:
	return {key: _text(pack.get(key), 500) for key in ("source_kind", "main_source_file") if pack.get(key)}


def _marker(text: str, pattern: str) -> Dict[str, Any]:
	match = re.search(pattern, text, flags=re.I)
	return {"present": bool(match), "evidence": text[max(0, match.start() - 180):match.end() + 320] if match else ""}


def build_evidence_pack_v2(evidence_pack: Dict[str, Any]) -> Dict[str, Any]:
	"""Normalize crawler output without importing the daily research pipeline."""
	if not isinstance(evidence_pack, dict) or not evidence_pack:
		return {}
	overview = _text(evidence_pack.get("section_overview"), 9000)
	intro = evidence_pack.get("intro_context") or evidence_pack.get("intro_claims")
	formulas = evidence_pack.get("formula_contexts") or evidence_pack.get("formula_evidence")
	variables = evidence_pack.get("variable_definitions") or evidence_pack.get("variables")
	method = evidence_pack.get("method_blocks") or evidence_pack.get("method_evidence")
	data = evidence_pack.get("data_sample_evidence") or evidence_pack.get("data_blocks")
	empirical = evidence_pack.get("empirical_setup_snippets") or evidence_pack.get("empirical_results")
	conclusion = evidence_pack.get("conclusion_context") or evidence_pack.get("conclusion_evidence")
	code = evidence_pack.get("code_or_algorithm_snippets") or evidence_pack.get("code_evidence")
	full_text = " ".join(_text(evidence_pack.get(key), 5000) for key in ("intro_context", "formula_contexts", "method_blocks", "data_sample_evidence", "empirical_setup_snippets", "conclusion_context", "missing_evidence"))
	return {
		"quality": evidence_pack.get("quality_checks") if isinstance(evidence_pack.get("quality_checks"), dict) else {},
		"section_map": [{"heading": _text(line.lstrip("- "), 180), "evidence_type": "section_map", **_anchor(evidence_pack)} for line in overview.splitlines()[:16] if _text(line.lstrip("- "))],
		"intro_claims": _list(intro), "formula_evidence": _list(formulas, text_limit=1400),
		"variable_definitions": _list(variables, text_limit=1000), "method_evidence": _list(method, text_limit=1600),
		"data_sample_evidence": _list(data, text_limit=1400), "empirical_results": _list(empirical, text_limit=1400),
		"experimental_formula_evidence": _list(evidence_pack.get("experimental_formula_contexts") or evidence_pack.get("experimental_formula_context"), 6, 1200),
		"code_evidence": _list(code, 6, 1000), "conclusion_evidence": _list(conclusion, 4, 1400),
		"missing_evidence": _list(evidence_pack.get("missing_evidence"), 12, 600),
		"excluded_sections": _text(evidence_pack.get("excluded_sections") or "references/appendix", 300),
		"evidence_presence": {"transaction_cost": _marker(full_text, r"transaction cost|trading cost|fee|slippage|成本|滑点|手续费"), "out_of_sample": _marker(full_text, r"out[- ]of[- ]sample|holdout|validation|walk[- ]forward|样本外|验证集"), "capacity": _marker(full_text, r"capacity|turnover|liquidity constraint|market impact|容量|换手|冲击成本"), "statistical_tests": _marker(full_text, r"t[- ]stat|p[- ]value|confidence|standard error|significant|显著|标准误|置信")},
	}

__all__ = ["build_evidence_pack_v2"]