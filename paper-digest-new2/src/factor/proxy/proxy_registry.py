"""Proxy registry loading, validation, and prompt context."""

from src.factor._legacy import legacy

_canonicalize_proxy_name = legacy._canonicalize_proxy_name
_load_proxy_registry = legacy._load_proxy_registry
_proxy_strength_rank = legacy._proxy_strength_rank
_validate_registry_proxy = legacy._validate_registry_proxy
_proxy_mapping_from_registry = legacy._proxy_mapping_from_registry
_resolve_proxy_variable = legacy._resolve_proxy_variable
_proxy_registry_prompt_line = legacy._proxy_registry_prompt_line
_proxy_registry_prompt_summary = legacy._proxy_registry_prompt_summary
_append_prompt_line_with_budget = legacy._append_prompt_line_with_budget
_proxy_registry_prompt_context_for_article = legacy._proxy_registry_prompt_context_for_article

__all__ = ["_load_proxy_registry", "_resolve_proxy_variable", "_proxy_registry_prompt_context_for_article"]