from __future__ import annotations

import json
import math
from typing import Any


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_zero(value: Any) -> bool:
    return _is_number(value) and float(value) == 0.0


def _is_one(value: Any) -> bool:
    return _is_number(value) and float(value) == 1.0


def _is_minus_one(value: Any) -> bool:
    return _is_number(value) and float(value) == -1.0


def _negate(value: Any) -> Any:
    if _is_number(value):
        return -float(value) if isinstance(value, float) else -value
    if isinstance(value, list) and len(value) == 2 and value[0] == "neg":
        return value[1]
    return ["neg", value]


def canonical_prefix(node: Any) -> Any:
    if isinstance(node, dict):
        op = node.get("op")
        args = node.get("args", [])
        if isinstance(op, str):
            return canonical_prefix([op, *args])
        return {key: canonical_prefix(value) for key, value in sorted(node.items())}
    if not isinstance(node, list) or not node:
        return node
    op = str(node[0])
    args = [canonical_prefix(arg) for arg in node[1:]]
    if op == "neg" and len(args) == 1:
        child = args[0]
        if isinstance(child, list) and child and child[0] == "neg" and len(child) == 2:
            return canonical_prefix(child[1])
        if isinstance(child, list) and len(child) == 3 and child[0] == "sub":
            return canonical_prefix(["sub", child[2], child[1]])
        if _is_zero(child):
            return 0
        return [op, child]
    if op in {"add", "mul"} and len(args) == 2:
        left, right = args
        if op == "add":
            if _is_zero(left):
                return right
            if _is_zero(right):
                return left
            if isinstance(left, list) and len(left) == 2 and left[0] == "neg" and prefix_equivalent(left[1], right):
                return 0
            if isinstance(right, list) and len(right) == 2 and right[0] == "neg" and prefix_equivalent(right[1], left):
                return 0
        if op == "mul":
            if _is_zero(left) or _is_zero(right):
                return 0
            if _is_one(left):
                return right
            if _is_one(right):
                return left
            if _is_minus_one(left):
                return canonical_prefix(["neg", right])
            if _is_minus_one(right):
                return canonical_prefix(["neg", left])
        return [op, *sorted(args, key=_stable_repr)]
    if op in {"sub", "div", "safe_div"} and len(args) == 2:
        left, right = args
        if op == "sub":
            if _is_zero(right):
                return left
            if _is_zero(left):
                return canonical_prefix(["neg", right])
            if prefix_equivalent(left, right):
                return 0
        if op in {"div", "safe_div"} and _is_one(right):
            return left
        return [op, left, right]
    if op in {"zscore", "rolling_mean", "rolling_std", "rolling_sum"} and len(args) == 2:
        value, window = args
        if op == "rolling_mean" and _is_one(window):
            return value
        return [op, value, window]
    return [op, *args]


def _stable_repr(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def canonical_prefix_key(node: Any) -> str:
    return _stable_repr(canonical_prefix(node))


def prefix_equivalent(left: Any, right: Any) -> bool:
    return canonical_prefix_key(left) == canonical_prefix_key(right)


def sign_equivalent(left: Any, right: Any) -> bool:
    return prefix_equivalent(left, right) or prefix_equivalent(left, _negate(right)) or prefix_equivalent(_negate(left), right)


def _numeric_series(candidate: dict[str, Any]) -> list[float]:
    for key in ("preview_values", "sample_values", "factor_values"):
        values = candidate.get(key)
        if not isinstance(values, list):
            continue
        series: list[float] = []
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                series.append(number)
        if len(series) >= 3:
            return series
    return []


def _correlation(left: list[float], right: list[float]) -> float | None:
    n = min(len(left), len(right))
    if n < 3:
        return None
    left = left[:n]
    right = right[:n]
    left_mean = sum(left) / n
    right_mean = sum(right) / n
    left_centered = [value - left_mean for value in left]
    right_centered = [value - right_mean for value in right]
    left_norm = math.sqrt(sum(value * value for value in left_centered))
    right_norm = math.sqrt(sum(value * value for value in right_centered))
    if left_norm == 0 or right_norm == 0:
        return None
    return sum(a * b for a, b in zip(left_centered, right_centered)) / (left_norm * right_norm)


def numeric_correlation_equivalent(parent_candidate: dict[str, Any], child_candidate: dict[str, Any], *, threshold: float = 0.999) -> bool:
    correlation = _correlation(_numeric_series(parent_candidate), _numeric_series(child_candidate))
    return correlation is not None and abs(correlation) >= threshold


def prefix_ops(node: Any) -> set[str]:
    ops: set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, list) and item:
            if isinstance(item[0], str):
                ops.add(item[0])
            for child in item[1:]:
                walk(child)
        elif isinstance(item, dict):
            op = item.get("op")
            if isinstance(op, str):
                ops.add(op)
            args = item.get("args", [])
            for child in args if isinstance(args, list) else [args]:
                walk(child)

    walk(node)
    return ops


def prefix_node_count(node: Any) -> int:
    if isinstance(node, list):
        return 1 + sum(prefix_node_count(item) for item in node[1:])
    if isinstance(node, dict):
        args = node.get("args", [])
        return 1 + sum(prefix_node_count(item) for item in args if isinstance(args, list))
    return 1


def is_empty_or_equivalent_mutation(parent_candidate: dict[str, Any], child_candidate: dict[str, Any]) -> bool:
    parent_prefix = parent_candidate.get("prefix_expression")
    child_prefix = child_candidate.get("prefix_expression")
    if parent_prefix is None or child_prefix is None:
        return False
    return prefix_equivalent(parent_prefix, child_prefix) or numeric_correlation_equivalent(parent_candidate, child_candidate)


__all__ = [
    "canonical_prefix",
    "canonical_prefix_key",
    "is_empty_or_equivalent_mutation",
    "numeric_correlation_equivalent",
    "prefix_equivalent",
    "prefix_node_count",
    "prefix_ops",
    "sign_equivalent",
]