from __future__ import annotations

from agent_alpha.factors.prefix_expression import (
    fields_from_prefix,
    prefix_to_expression,
    validate_prefix_expression,
    windows_from_prefix,
)
from agent_alpha.rag.field_registry import FieldRegistry


def test_prefix_expression_converts_to_compat_expression() -> None:
    prefix = ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]]

    assert prefix_to_expression(prefix) == "safe_div((bidV1 - askV1), (bidV1 + askV1))"
    assert fields_from_prefix(prefix) == ["bidV1", "askV1"]


def test_prefix_expression_extracts_windows() -> None:
    prefix = ["zscore", ["rolling_mean", "volume", 20], 60]

    assert windows_from_prefix(prefix) == [20, 60]


def test_prefix_expression_rejects_label_leakage() -> None:
    registry = FieldRegistry.from_yaml("configs/field_registry.yaml")

    result = validate_prefix_expression(["rolling_mean", "ret60s", 20], registry)

    assert not result.ok
    assert "label field not allowed: ret60s" in result.errors


def test_prefix_expression_rejects_unknown_op() -> None:
    registry = FieldRegistry.from_yaml("configs/field_registry.yaml")

    result = validate_prefix_expression(["mystery_op", "bidV1"], registry)

    assert not result.ok
    assert "unsupported prefix op: mystery_op" in result.errors


def test_prefix_expression_supports_safe_extra_ops() -> None:
    registry = FieldRegistry.from_yaml("configs/field_registry.yaml")
    prefix = ["rank", ["log1p", ["abs", ["clip", "volume", 0, 1000]]]]

    result = validate_prefix_expression(prefix, registry)

    assert result.ok, result.errors
    assert prefix_to_expression(prefix) == "rank(log1p(abs(clip(volume, 0, 1000))))"
    assert fields_from_prefix(prefix) == ["volume"]
