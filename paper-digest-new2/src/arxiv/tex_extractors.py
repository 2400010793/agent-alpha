"""TeX evidence extractors for intro, formulas, methods, code, and conclusion."""

from ._legacy import legacy

_extract_tex_method_blocks = legacy._extract_tex_method_blocks
_extract_tex_intro_context = legacy._extract_tex_intro_context
_extract_tex_formula_contexts = legacy._extract_tex_formula_contexts
_extract_tex_empirical_setup_snippets = legacy._extract_tex_empirical_setup_snippets
_extract_tex_conclusion_context = legacy._extract_tex_conclusion_context
_extract_tex_code_or_algorithm_snippets = legacy._extract_tex_code_or_algorithm_snippets
_extract_tex_experimental_formula_contexts = legacy._extract_tex_experimental_formula_contexts
_extract_tex_include_audit = legacy._extract_tex_include_audit
_tex_noise_residual_audit = legacy._tex_noise_residual_audit

__all__ = [
    "_extract_tex_intro_context",
    "_extract_tex_formula_contexts",
    "_extract_tex_method_blocks",
    "_extract_tex_conclusion_context",
    "_extract_tex_code_or_algorithm_snippets",
]