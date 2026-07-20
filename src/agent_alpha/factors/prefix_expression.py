from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_alpha.rag.field_registry import FieldRegistry


PREFIX_ARITY: dict[str, tuple[int, int]] = {
    "add": (2, 2),
    "sub": (2, 2),
    "mul": (2, 2),
    "div": (2, 2),
    "neg": (1, 1),
    "safe_div": (2, 2),
    "zscore": (1, 2),
    "rolling_mean": (2, 2),
    "rolling_std": (2, 2),
    "rolling_sum": (2, 2),
    "abs": (1, 1),
    "clip": (3, 3),
    "log1p": (1, 1),
    "log": (1, 1),
    "tanh": (1, 1),
    "sign": (1, 1),
    "rank": (1, 1),
    "max": (2, 2),
    "min": (2, 2),
    "gt": (2, 2),
    "lt": (2, 2),
    "ge": (2, 2),
    "le": (2, 2),
    "eq": (2, 2),
    "neq": (2, 2),
    "and": (2, 2),
    "or": (2, 2),
    "where": (3, 3),
    "diff": (2, 2),
    "shift": (2, 2),
    "pct_change": (2, 2),
    "ewm_mean": (2, 2),
    "ewm_std": (2, 2),
    "rolling_min": (2, 2),
    "rolling_max": (2, 2),
    "rolling_median": (2, 2),
    "rolling_rank": (2, 2),
    "rolling_count": (2, 2),
    "rolling_corr": (3, 3),
    "rolling_cov": (3, 3),
    "rolling_beta": (3, 3),
    "div_mean": (3, 3),
    "div_std": (3, 3),
    "vol_scale": (2, 2),
}


WINDOW_OPS = {
    "zscore",
    "rolling_mean",
    "rolling_std",
    "rolling_sum",
    "rolling_min",
    "rolling_max",
    "rolling_median",
    "rolling_rank",
    "rolling_count",
    "ewm_mean",
    "ewm_std",
    "diff",
    "shift",
    "pct_change",
    "vol_scale",
}

TWO_INPUT_WINDOW_OPS = {"rolling_corr", "rolling_cov", "rolling_beta", "div_mean", "div_std"}


@dataclass
class PrefixValidationResult:
    ok: bool
    used_fields: list[str] = field(default_factory=list)
    windows: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _node_op_args(node: Any) -> tuple[str, list[Any]]:
    if isinstance(node, list) and node:
        return str(node[0]), list(node[1:])
    if isinstance(node, dict):
        op = str(node.get("op") or "")
        args = node.get("args", [])
        if not isinstance(args, list):
            args = [args]
        return op, list(args)
    raise ValueError(f"invalid prefix node: {node!r}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def fields_from_prefix(node: Any) -> list[str]:
    fields: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            fields.append(item)
            return
        if _is_number(item):
            return
        op, args = _node_op_args(item)
        if op in WINDOW_OPS and len(args) == 2 and _is_number(args[1]):
            walk(args[0])
            return
        if op in TWO_INPUT_WINDOW_OPS and len(args) == 3 and _is_number(args[2]):
            walk(args[0])
            walk(args[1])
            return
        if op == "clip" and len(args) == 3 and _is_number(args[1]) and _is_number(args[2]):
            walk(args[0])
            return
        for arg in args:
            walk(arg)

    walk(node)
    return list(dict.fromkeys(fields))


def windows_from_prefix(node: Any) -> list[int]:
    windows: list[int] = []

    def walk(item: Any) -> None:
        if isinstance(item, str) or _is_number(item):
            return
        op, args = _node_op_args(item)
        if op in WINDOW_OPS and len(args) == 2:
            if _is_number(args[1]):
                windows.append(int(args[1]))
            walk(args[0])
            return
        if op in TWO_INPUT_WINDOW_OPS and len(args) == 3:
            if _is_number(args[2]):
                windows.append(int(args[2]))
            walk(args[0])
            walk(args[1])
            return
        if op == "clip" and len(args) == 3:
            walk(args[0])
            return
        for arg in args:
            walk(arg)

    walk(node)
    return sorted(set(windows))


def prefix_to_expression(node: Any) -> str:
    if isinstance(node, str):
        return node
    if _is_number(node):
        return repr(node)
    op, args = _node_op_args(node)
    if op == "add":
        return f"({prefix_to_expression(args[0])} + {prefix_to_expression(args[1])})"
    if op == "sub":
        return f"({prefix_to_expression(args[0])} - {prefix_to_expression(args[1])})"
    if op == "mul":
        return f"({prefix_to_expression(args[0])} * {prefix_to_expression(args[1])})"
    if op == "div":
        return f"({prefix_to_expression(args[0])} / {prefix_to_expression(args[1])})"
    if op == "neg":
        return f"(-{prefix_to_expression(args[0])})"
    if op == "safe_div":
        return f"safe_div({prefix_to_expression(args[0])}, {prefix_to_expression(args[1])})"
    if op in {"zscore", "rolling_mean", "rolling_std", "rolling_sum", "rolling_min", "rolling_max", "rolling_median", "rolling_rank", "rolling_count", "diff", "shift", "pct_change", "vol_scale"}:
        return f"{op}({prefix_to_expression(args[0])}, {int(args[1])})"
    if op == "ewm_mean":
        return f"ewma({prefix_to_expression(args[0])}, {int(args[1])})"
    if op == "ewm_std":
        return f"ewm_std({prefix_to_expression(args[0])}, {int(args[1])})"
    if op in {"rolling_corr", "rolling_cov", "rolling_beta", "div_mean", "div_std"}:
        return f"{op}({prefix_to_expression(args[0])}, {prefix_to_expression(args[1])}, {int(args[2])})"
    if op == "abs":
        return f"abs({prefix_to_expression(args[0])})"
    if op == "clip":
        return f"clip({prefix_to_expression(args[0])}, {args[1]!r}, {args[2]!r})"
    if op == "log1p":
        return f"log1p({prefix_to_expression(args[0])})"
    if op == "log":
        return f"log({prefix_to_expression(args[0])})"
    if op == "tanh":
        return f"tanh({prefix_to_expression(args[0])})"
    if op == "sign":
        return f"sign({prefix_to_expression(args[0])})"
    if op == "rank":
        return f"rank({prefix_to_expression(args[0])})"
    if op == "max":
        return f"max({prefix_to_expression(args[0])}, {prefix_to_expression(args[1])})"
    if op == "min":
        return f"min({prefix_to_expression(args[0])}, {prefix_to_expression(args[1])})"
    if op == "gt":
        return f"({prefix_to_expression(args[0])} > {prefix_to_expression(args[1])})"
    if op == "lt":
        return f"({prefix_to_expression(args[0])} < {prefix_to_expression(args[1])})"
    if op == "ge":
        return f"({prefix_to_expression(args[0])} >= {prefix_to_expression(args[1])})"
    if op == "le":
        return f"({prefix_to_expression(args[0])} <= {prefix_to_expression(args[1])})"
    if op == "eq":
        return f"({prefix_to_expression(args[0])} == {prefix_to_expression(args[1])})"
    if op == "neq":
        return f"({prefix_to_expression(args[0])} != {prefix_to_expression(args[1])})"
    if op == "and":
        return f"({prefix_to_expression(args[0])} & {prefix_to_expression(args[1])})"
    if op == "or":
        return f"({prefix_to_expression(args[0])} | {prefix_to_expression(args[1])})"
    if op == "where":
        return f"where({prefix_to_expression(args[0])}, {prefix_to_expression(args[1])}, {prefix_to_expression(args[2])})"
    raise ValueError(f"unsupported prefix op: {op}")


def validate_prefix_expression(node: Any, registry: FieldRegistry | None = None) -> PrefixValidationResult:
    registry = registry or FieldRegistry.from_yaml()
    errors: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            if registry.is_label(item):
                errors.append(f"label field not allowed: {item}")
            elif registry.is_blocked(item):
                errors.append(f"blocked field not allowed: {item}")
            elif not registry.is_allowed_input(item):
                errors.append(f"unknown field: {item}")
            return
        if _is_number(item):
            return
        try:
            op, args = _node_op_args(item)
        except ValueError as exc:
            errors.append(str(exc))
            return
        if op not in PREFIX_ARITY:
            errors.append(f"unsupported prefix op: {op}")
            return
        min_arity, max_arity = PREFIX_ARITY[op]
        if not (min_arity <= len(args) <= max_arity):
            errors.append(f"invalid arity for {op}: {len(args)}")
            return
        if op in WINDOW_OPS and len(args) == 2:
            if not _is_number(args[1]) or int(args[1]) <= 0 or int(args[1]) > 7200:
                errors.append(f"invalid window for {op}: {args[1]!r}")
            walk(args[0])
            return
        if op in TWO_INPUT_WINDOW_OPS and len(args) == 3:
            if not _is_number(args[2]) or int(args[2]) <= 0 or int(args[2]) > 7200:
                errors.append(f"invalid window for {op}: {args[2]!r}")
            walk(args[0])
            walk(args[1])
            return
        if op == "clip":
            if not _is_number(args[1]) or not _is_number(args[2]):
                errors.append(f"invalid clip bounds: {args[1]!r}, {args[2]!r}")
            walk(args[0])
            return
        for arg in args:
            walk(arg)

    walk(node)
    return PrefixValidationResult(
        ok=not errors,
        used_fields=fields_from_prefix(node) if not errors else [],
        windows=windows_from_prefix(node) if not errors else [],
        errors=errors,
    )