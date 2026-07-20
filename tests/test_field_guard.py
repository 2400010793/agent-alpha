from __future__ import annotations

from agent_alpha.factors.field_guard import validate_factor_expression
from agent_alpha.rag.field_registry import FieldRegistry


def test_validate_factor_expression_accepts_allowed_hf_fields() -> None:
    registry = FieldRegistry.from_yaml("configs/field_registry.yaml")
    result = validate_factor_expression("zscore(bidV1 - askV1) + rolling_mean(volume, 20)", registry)
    assert result.ok
    assert set(result.used_fields) == {"bidV1", "askV1", "volume"}


def test_validate_factor_expression_rejects_forward_label_leakage() -> None:
    registry = FieldRegistry.from_yaml("configs/field_registry.yaml")
    result = validate_factor_expression("rolling_mean(ret60s, 10) + volume", registry)
    assert not result.ok
    assert result.label_leakage_fields == ["ret60s"]


def test_validate_factor_expression_rejects_blocked_fields() -> None:
    registry = FieldRegistry.from_yaml("configs/field_registry.yaml")
    result = validate_factor_expression("volume + analyst_rating", registry)
    assert not result.ok
    assert result.blocked_fields == ["analyst_rating"]


def test_validate_factor_expression_accepts_whitelisted_derived_fields() -> None:
    registry = FieldRegistry.from_yaml("configs/field_registry.yaml")
    result = validate_factor_expression("zscore(mid_price_l1) + spread_l1", registry)
    assert result.ok
    assert set(result.used_fields) == {"mid_price_l1", "spread_l1"}