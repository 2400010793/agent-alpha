from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent_alpha.factors.field_guard import FieldValidationResult, validate_factor_expression
from agent_alpha.factors.factor_schema import FactorCandidate
from agent_alpha.factors.prefix_expression import validate_prefix_expression
from agent_alpha.rag.field_registry import FieldRegistry


_WINDOW_RE = re.compile(r"\b(?:rolling_mean|rolling_std|rolling_sum|rolling_corr|zscore|ewma)\s*\([^)]*,\s*(\d+)\s*\)")


@dataclass
class CandidateValidationResult:
    ok: bool
    field_result: FieldValidationResult
    window_errors: list[str] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        parts = []
        if self.field_result.message != "ok":
            parts.append(self.field_result.message)
        parts.extend(self.window_errors)
        parts.extend(self.schema_errors)
        return "; ".join(parts) if parts else "ok"


def validate_candidate_expression(expression: str, registry: FieldRegistry | None = None) -> FieldValidationResult:
    return validate_factor_expression(expression, registry or FieldRegistry.from_yaml())


def extract_windows(expression: str) -> list[int]:
    return [int(match) for match in _WINDOW_RE.findall(expression)]


def validate_factor_candidate(candidate: dict | FactorCandidate, registry: FieldRegistry | None = None) -> CandidateValidationResult:
    factor = candidate if isinstance(candidate, FactorCandidate) else FactorCandidate.from_mapping(candidate)
    registry = registry or FieldRegistry.from_yaml()
    prefix_result = validate_prefix_expression(factor.prefix_expression, registry) if factor.prefix_expression is not None else None
    if prefix_result is not None:
        field_result = FieldValidationResult(ok=prefix_result.ok and bool(prefix_result.used_fields), used_fields=prefix_result.used_fields, message="ok" if prefix_result.ok and prefix_result.used_fields else "no allowed input fields found")
    else:
        field_result = validate_candidate_expression(factor.expression, registry=registry)
    schema_errors: list[str] = []
    if not factor.factor_id:
        schema_errors.append("missing factor_id")
    if not factor.name:
        schema_errors.append("missing name")
    if not factor.expression and factor.prefix_expression is None:
        schema_errors.append("missing expression")
    if not factor.fields:
        schema_errors.append("missing input fields")
    for field_name in factor.fields:
        if registry.is_label(field_name):
            schema_errors.append(f"field list contains label field: {field_name}")
        elif registry.is_blocked(field_name):
            schema_errors.append(f"field list contains blocked field: {field_name}")
        elif not registry.is_allowed_input(field_name):
            schema_errors.append(f"field list contains unknown field: {field_name}")
    if prefix_result is not None and not prefix_result.ok:
        schema_errors.extend(prefix_result.errors)
    windows = sorted(set(factor.windows + extract_windows(factor.expression) + (prefix_result.windows if prefix_result else [])))
    window_errors = [f"invalid window:{window}" for window in windows if window <= 0 or window > 7200]
    ok = field_result.ok and not schema_errors and not window_errors
    return CandidateValidationResult(ok=ok, field_result=field_result, window_errors=window_errors, schema_errors=schema_errors)