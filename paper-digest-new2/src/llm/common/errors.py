"""LLM exception and rate-limit helpers."""

from src.llm._legacy import daily

LLMCallLimitReached = daily.LLMCallLimitReached
LLMRateLimitReached = daily.LLMRateLimitReached
_is_rate_limit_error = daily._is_rate_limit_error
_is_nonretryable_llm_output_error = daily._is_nonretryable_llm_output_error
_summarize_llm_error = daily._summarize_llm_error

__all__ = ["LLMCallLimitReached", "LLMRateLimitReached"]