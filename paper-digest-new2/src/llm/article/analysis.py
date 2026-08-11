"""Single-stage article analysis and cache orchestration."""

from src.llm._legacy import daily

_heuristic_structured_summary = daily._heuristic_structured_summary
analyze_article = daily.analyze_article
llm_analyze_article = daily.llm_analyze_article
ensure_analysis_fields = daily.ensure_analysis_fields
_has_complete_analysis_fields = daily._has_complete_analysis_fields
_analysis_cache_key = daily._analysis_cache_key
analyze_rows_with_cache = daily.analyze_rows_with_cache
_reserve_llm_call = daily._reserve_llm_call
_mark_pending_llm = daily._mark_pending_llm

__all__ = ["analyze_article", "llm_analyze_article", "ensure_analysis_fields", "analyze_rows_with_cache"]