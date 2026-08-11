"""LLM scoring helpers independent of the old daily pipeline."""
from __future__ import annotations

import re
from typing import Any, Dict

SCORE_DIMENSIONS = (("relevance", "相关性"), ("mechanism", "机制可信度"), ("statistical", "统计可信度"), ("implementation", "可实现性"), ("cost_sensitivity", "成本敏感性"), ("generality", "普适性"))

def _normalize_text(value: Any) -> str:
	return re.sub(r"\s+", " ", str(value or "")).strip()

def _clamp_score(value: Any) -> int:
	try: score = int(round(float(value)))
	except (TypeError, ValueError): score = 0
	return max(0, min(10, score))

def normalize_dimension_scores(raw: Any) -> Dict[str, Dict[str, Any]]:
	payload = raw if isinstance(raw, dict) else {}
	return {key: {"label": label, "score": _clamp_score((payload.get(key) or {}).get("score", 0) if isinstance(payload.get(key), dict) else 0), "comment": _normalize_text((payload.get(key) or {}).get("comment", ""))[:520] if isinstance(payload.get(key), dict) else "", "evidence": _normalize_text((payload.get(key) or {}).get("evidence", ""))[:260] if isinstance(payload.get(key), dict) else "", "critique": _normalize_text((payload.get(key) or {}).get("critique", ""))[:520] if isinstance(payload.get(key), dict) else ""} for key, label in SCORE_DIMENSIONS}

def normalize_structured_summary(raw: Any) -> Dict[str, str]:
	payload = raw if isinstance(raw, dict) else {}
	return {key: _normalize_text(payload.get(key, ""))[:900] for key in ("problem", "method", "data", "author_claim", "limitations", "critical_assessment", "missing_tests", "key_results") if _normalize_text(payload.get(key, ""))}

def mean_recommendation_score(scores: Dict[str, Dict[str, Any]]) -> float:
	values = [float(item.get("score", 0)) for item in scores.values() if isinstance(item, dict)]
	return round(sum(values) / len(values), 1) if values else 0.0

_normalize_dimension_scores = normalize_dimension_scores
_normalize_structured_summary = normalize_structured_summary
_mean_recommendation_score = mean_recommendation_score
__all__ = ["normalize_dimension_scores", "normalize_structured_summary", "mean_recommendation_score", "_normalize_dimension_scores", "_normalize_structured_summary", "_mean_recommendation_score"]