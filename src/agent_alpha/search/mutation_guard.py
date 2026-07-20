from __future__ import annotations

import json
from typing import Any


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_zero(value: Any) -> bool:
    return _is_number(value) and float(value) == 0.0


def _is_one(value: Any) -> bool:
    return _is_number(value) and float(value) == 1.0


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
        if op == "mul":
            if _is_zero(left) or _is_zero(right):
                return 0
            if _is_one(left):
                return right
            if _is_one(right):
                return left
        return [op, *sorted(args, key=_stable_repr)]
    if op in {"sub", "div", "safe_div"} and len(args) == 2:
        left, right = args
        if op == "sub" and _is_zero(right):
            return left
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
    return prefix_equivalent(parent_prefix, child_prefix)


__all__ = [
    "canonical_prefix",
    "canonical_prefix_key",
    "is_empty_or_equivalent_mutation",
    "prefix_equivalent",
    "prefix_node_count",
    "prefix_ops",
]