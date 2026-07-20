from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_alpha.factors.expression_validator import validate_factor_candidate
from agent_alpha.factors.factor_schema import FactorCandidate
from agent_alpha.factors.prefix_expression import fields_from_prefix, prefix_to_expression, windows_from_prefix
from agent_alpha.rag.field_registry import FieldRegistry


PREFIX_OP_ALIASES = {
    "Add": "add",
    "Sum": "add",
    "sum": "add",
    "plus": "add",
    "Sub": "sub",
    "subtract": "sub",
    "Mul": "mul",
    "Mult": "mul",
    "mult": "mul",
    "multiply": "mul",
    "Div": "div",
    "divide": "div",
    "SafeDiv": "safe_div",
    "safeDiv": "safe_div",
    "Neg": "neg",
    "Abs": "abs",
    "ZScore": "zscore",
    "RollingZScore": "zscore",
    "RollingMean": "rolling_mean",
    "RollingStd": "rolling_std",
    "RollingSum": "rolling_sum",
    "Clip": "clip",
    "Log1p": "log1p",
    "Log": "log",
    "Tanh": "tanh",
    "Sign": "sign",
    "Rank": "rank",
    "Maximum": "max",
    "maximum": "max",
    "Max": "max",
    "Minimum": "min",
    "minimum": "min",
    "Min": "min",
    "Gt": "gt",
    "Lt": "lt",
    "Ge": "ge",
    "Le": "le",
    "Eq": "eq",
    "Neq": "neq",
    "And": "and",
    "Or": "or",
    "Where": "where",
    "IfElse": "where",
    "Diff": "diff",
    "Shift": "shift",
    "PctChange": "pct_change",
    "EwmMean": "ewm_mean",
    "EwmStd": "ewm_std",
    "RollingMin": "rolling_min",
    "RollingMax": "rolling_max",
    "RollingMedian": "rolling_median",
    "RollingRank": "rolling_rank",
    "TsRank": "rolling_rank",
    "RollingCount": "rolling_count",
    "Corr": "rolling_corr",
    "Cov": "rolling_cov",
    "Beta": "rolling_beta",
    "DivMean": "div_mean",
    "DivStd": "div_std",
    "VolScale": "vol_scale",
}


@dataclass(frozen=True)
class CandidateQualification:
    ok: bool
    candidate: dict[str, Any] | None = None
    message: str = ""


def normalize_llm_prefix(value: Any) -> Any:
    """Normalize repairable ASL quirks without inventing unsupported structure."""
    if isinstance(value, list) and value:
        normalized = [normalize_llm_prefix(item) for item in value]
        if isinstance(normalized[0], str):
            normalized[0] = PREFIX_OP_ALIASES.get(normalized[0], normalized[0])
        return normalized
    if isinstance(value, dict):
        normalized = {key: normalize_llm_prefix(item) for key, item in value.items()}
        op = normalized.get("op")
        if isinstance(op, str):
            normalized["op"] = PREFIX_OP_ALIASES.get(op, op)
        if normalized.get("op") and "args" not in normalized:
            args: list[Any] = []
            if "x" in normalized:
                args.append(normalized["x"])
            if "y" in normalized:
                args.append(normalized["y"])
            window = normalized.get("window", normalized.get("halflife", normalized.get("periods")))
            if window is not None:
                args.append(normalize_llm_prefix(window))
            if args:
                normalized["args"] = args
        return normalized
    if isinstance(value, str):
        text = value.strip()
        try:
            if any(marker in text for marker in (".", "e", "E")):
                return float(text)
            return int(text)
        except ValueError:
            return value
    return value


def sync_prefix_derived_fields(candidate: dict[str, Any]) -> None:
    prefix_expression = candidate.get("prefix_expression")
    if prefix_expression is None:
        return
    prefix_expression = normalize_llm_prefix(prefix_expression)
    candidate["prefix_expression"] = prefix_expression
    try:
        candidate["expression"] = prefix_to_expression(prefix_expression)
        candidate["fields"] = fields_from_prefix(prefix_expression)
        candidate["windows"] = windows_from_prefix(prefix_expression)
    except (IndexError, TypeError, ValueError):
        return


def qualify_factor_candidate_payload(payload: dict[str, Any], registry: FieldRegistry | None = None) -> CandidateQualification:
    registry = registry or FieldRegistry.from_yaml()
    candidate_payload = dict(payload)
    sync_prefix_derived_fields(candidate_payload)
    try:
        candidate = FactorCandidate.from_mapping(candidate_payload)
    except (TypeError, ValueError) as exc:
        return CandidateQualification(ok=False, message=str(exc))
    validation = validate_factor_candidate(candidate, registry=registry)
    if not validation.ok:
        return CandidateQualification(ok=False, message=validation.message)
    return CandidateQualification(ok=True, candidate=candidate.to_dict(), message="ok")


def admit_factor_candidate_with_mcp(payload: dict[str, Any], *, role: str = "The Implementer") -> CandidateQualification:
    from agent_alpha.mcp_tools.tool_router import call_tool

    envelope = call_tool("factor.render_and_compile_candidate", {"candidate": payload}, role=role)
    results = envelope.get("results", {}) if isinstance(envelope, dict) else {}
    if not isinstance(results, dict):
        return CandidateQualification(ok=False, message="invalid MCP admission result")
    if not results.get("ok"):
        return CandidateQualification(ok=False, candidate=results.get("candidate"), message=str(results.get("message") or results.get("stage") or "MCP admission failed"))
    return CandidateQualification(ok=True, candidate=results.get("candidate"), message="ok")


__all__ = ["CandidateQualification", "admit_factor_candidate_with_mcp", "normalize_llm_prefix", "qualify_factor_candidate_payload", "sync_prefix_derived_fields"]