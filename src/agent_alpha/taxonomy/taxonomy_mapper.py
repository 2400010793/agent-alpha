from __future__ import annotations


def map_hf_tags_to_roles(tags: list[str]) -> list[str]:
    """Map HF mechanism tags to reusable CogAlpha-style roles.

    TODO: move mapping to config once role selection is stabilized.
    """
    mapping = {
        "order_book_pressure": "AgentOrderImbalance",
        "depute_imbalance": "AgentOrderImbalance",
        "trade_impact": "AgentVolumeStructure",
        "price_volume_divergence": "AgentPriceVolumeCoherence",
        "spread_liquidity": "AgentLiquidity",
        "short_reversal": "AgentReversal",
        "short_momentum": "AgentDailyTrend",
        "volatility_burst": "AgentVolatilityRegime",
        "book_shape": "AgentBarShape",
        "trading_rhythm": "AgentVolumeStructure",
    }
    return sorted({mapping[tag] for tag in tags if tag in mapping})