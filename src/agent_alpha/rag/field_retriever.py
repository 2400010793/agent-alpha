from __future__ import annotations

from typing import Any

from agent_alpha.rag.field_registry import FieldRegistry


RUNTIME_SAFE_DERIVED_FIELDS = {
    "spread_l1",
    "relative_spread_l1",
    "mid_price_l1",
    "microprice_l1",
    "depth_imbalance_l1",
    "log_volume",
    "volume_shock_20_120",
    "activity_surge_20_120",
}


TAG_FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "order_book_pressure": ("bidV1", "askV1", "bidP1", "askP1", "depth_imbalance_l1", "spread_l1", "relative_spread_l1"),
    "depute_imbalance": ("totalDeputeBuy", "totalDeputeSell", "averageBuy", "averageSell", "bidV1", "askV1", "depth_imbalance_l1"),
    "hidden_liquidity": ("totalDeputeBuy", "totalDeputeSell", "averageBuy", "averageSell", "bidV1", "askV1", "depth_imbalance_l1"),
    "spread_liquidity": ("askP1", "bidP1", "askV1", "bidV1", "spread_l1", "relative_spread_l1", "microprice_l1"),
    "trade_impact": ("volume", "money", "close", "log_volume", "activity_surge_20_120", "volume_shock_20_120"),
    "price_volume_divergence": ("close", "volume", "money", "log_volume", "volume_shock_20_120"),
    "volatility_burst": ("close", "volume", "money", "spread_l1", "relative_spread_l1", "activity_surge_20_120"),
    "short_reversal": ("close", "volume", "money", "spread_l1", "depth_imbalance_l1"),
    "short_momentum": ("close", "volume", "money", "microprice_l1", "depth_imbalance_l1"),
    "book_shape": ("askP1", "askP10", "bidP1", "bidP10", "askV1", "askV10", "bidV1", "bidV10"),
    "trading_rhythm": ("volume", "money", "log_volume", "activity_surge_20_120", "volume_shock_20_120"),
}


TEXT_FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "spread": ("spread_l1", "relative_spread_l1", "askP1", "bidP1"),
    "liquidity": ("bidV1", "askV1", "spread_l1", "relative_spread_l1"),
    "depth": ("bidV1", "askV1", "depth_imbalance_l1"),
    "imbalance": ("bidV1", "askV1", "depth_imbalance_l1"),
    "depute": ("totalDeputeBuy", "totalDeputeSell", "averageBuy", "averageSell"),
    "hidden": ("totalDeputeBuy", "totalDeputeSell", "averageBuy", "averageSell"),
    "volume": ("volume", "log_volume", "volume_shock_20_120", "activity_surge_20_120"),
    "money": ("money", "log_volume"),
    "price": ("close", "askP1", "bidP1", "mid_price_l1", "microprice_l1"),
    "microprice": ("microprice_l1", "askP1", "bidP1", "askV1", "bidV1"),
    "volatility": ("close", "spread_l1", "relative_spread_l1", "activity_surge_20_120"),
    "reversal": ("close", "volume", "spread_l1", "depth_imbalance_l1"),
    "momentum": ("close", "volume", "money", "microprice_l1"),
}


def _as_strings(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _signal_text(signal: dict[str, Any]) -> str:
    keys = ("signal_id", "signal_name", "market_intuition", "hypothesis", "expected_direction")
    return " ".join(str(signal.get(key) or "") for key in keys).casefold()


def _field_allowed(field: str, registry: FieldRegistry, *, runtime_safe_only: bool) -> bool:
    if registry.is_label(field) or registry.is_blocked(field):
        return False
    if field in registry.allowed_input_fields:
        return field not in {"code", "ticker", "date", "delay_time", "processing_time"}
    if field in registry.derived_feature_fields:
        return not runtime_safe_only or field in RUNTIME_SAFE_DERIVED_FIELDS
    return False


def recommend_fields_for_signal(
    signal: dict[str, Any],
    *,
    registry: FieldRegistry | None = None,
    limit: int = 20,
    runtime_safe_only: bool = True,
) -> dict[str, Any]:
    registry = registry or FieldRegistry.from_yaml()
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    def add(field: str, score: float, reason: str) -> None:
        if not _field_allowed(field, registry, runtime_safe_only=runtime_safe_only):
            return
        scores[field] = scores.get(field, 0.0) + score
        reasons.setdefault(field, []).append(reason)

    for field in _as_strings(signal.get("candidate_fields")):
        add(field, 3.0, "candidate_fields")
    for tag in _as_strings(signal.get("hf_mechanism_tags")):
        for field in TAG_FIELD_HINTS.get(tag, ()): 
            add(field, 2.0, f"mechanism_tag:{tag}")
    text = _signal_text(signal)
    for keyword, fields in TEXT_FIELD_HINTS.items():
        if keyword in text:
            for field in fields:
                add(field, 1.0, f"text_keyword:{keyword}")
    for fallback in ("close", "volume", "money", "bidV1", "askV1", "bidP1", "askP1"):
        add(fallback, 0.2, "fallback_liquid_raw_field")

    ranked = sorted(scores, key=lambda field: (-scores[field], field))[: max(1, limit)]
    recommended = [{"field": field, "score": round(scores[field], 4), "reasons": reasons.get(field, [])} for field in ranked]
    return {
        "recommended_fields": recommended,
        "recommended_field_names": [item["field"] for item in recommended],
        "runtime_safe_derived_fields": sorted(RUNTIME_SAFE_DERIVED_FIELDS),
        "forbidden_label_fields": sorted(registry.label_fields),
        "blocked_fields": sorted(registry.blocked_fields),
        "runtime_safe_only": runtime_safe_only,
    }


__all__ = ["RUNTIME_SAFE_DERIVED_FIELDS", "recommend_fields_for_signal"]