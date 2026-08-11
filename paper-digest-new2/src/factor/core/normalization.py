"""Paper HF factor and candidate normalization."""

from src.factor._legacy import legacy

_safe_factor_field = legacy._safe_factor_field
_normalize_string_list = legacy._normalize_string_list
_normalize_paper_hf_formula_plan = legacy._normalize_paper_hf_formula_plan
normalize_paper_hf_factors = legacy.normalize_paper_hf_factors
normalize_factor_candidates = legacy.normalize_factor_candidates
_paper_factors_for_row = legacy._paper_factors_for_row
_strict_paper_hf_factors_for_row = legacy._strict_paper_hf_factors_for_row

__all__ = ["normalize_paper_hf_factors", "normalize_factor_candidates"]