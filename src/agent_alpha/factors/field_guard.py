from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent_alpha.rag.field_registry import FieldRegistry


_TOKEN_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_PYTHON_WORDS = {
    "and",
    "or",
    "not",
    "if",
    "else",
    "True",
    "False",
    "None",
    "df",
    "features",
    "np",
    "pd",
}


@dataclass
class FieldValidationResult:
    ok: bool
    used_fields: list[str] = field(default_factory=list)
    blocked_fields: list[str] = field(default_factory=list)
    label_leakage_fields: list[str] = field(default_factory=list)
    unknown_fields: list[str] = field(default_factory=list)
    message: str = ""


def extract_expression_tokens(expression: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(expression):
        if token in seen or token in _PYTHON_WORDS:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def validate_factor_expression(expression: str, registry: FieldRegistry) -> FieldValidationResult:
    tokens = extract_expression_tokens(expression)
    functions = registry.allowed_functions
    used_fields: list[str] = []
    blocked: list[str] = []
    leakage: list[str] = []
    unknown: list[str] = []
    for token in tokens:
        if token in functions:
            continue
        if registry.is_blocked(token):
            blocked.append(token)
        elif registry.is_label(token):
            leakage.append(token)
        elif registry.is_allowed_input(token):
            used_fields.append(token)
        else:
            unknown.append(token)
    ok = not blocked and not leakage and not unknown and bool(used_fields)
    problems = []
    if blocked:
        problems.append(f"blocked fields: {', '.join(blocked)}")
    if leakage:
        problems.append(f"forward label leakage: {', '.join(leakage)}")
    if unknown:
        problems.append(f"unknown fields/functions: {', '.join(unknown)}")
    if not used_fields:
        problems.append("no allowed input fields found")
    return FieldValidationResult(
        ok=ok,
        used_fields=used_fields,
        blocked_fields=blocked,
        label_leakage_fields=leakage,
        unknown_fields=unknown,
        message="; ".join(problems) if problems else "ok",
    )