from __future__ import annotations

from typing import Any

import numpy as np


def safe_divide(numerator: Any, denominator: Any, eps: float = 1e-12) -> Any:
    return numerator / (denominator + eps)


def add_basic_hf_features(frame):
    """Add stable high-frequency derived features used by controlled renderers."""
    df = frame.copy()
    if "askP1" in df and "bidP1" in df:
        df["spread_l1"] = df["askP1"] - df["bidP1"]
        df["mid_price_l1"] = (df["askP1"] + df["bidP1"]) / 2.0
        df["relative_spread_l1"] = safe_divide(df["spread_l1"], df["mid_price_l1"])
    if "askV1" in df and "bidV1" in df:
        df["depth_imbalance_l1"] = safe_divide(df["bidV1"] - df["askV1"], df["bidV1"] + df["askV1"])
        if "askP1" in df and "bidP1" in df:
            df["microprice_l1"] = safe_divide(df["askP1"] * df["bidV1"] + df["bidP1"] * df["askV1"], df["askV1"] + df["bidV1"])
    if "totalDeputeBuy" in df and "totalDeputeSell" in df:
        df["depute_imbalance"] = safe_divide(
            df["totalDeputeBuy"] - df["totalDeputeSell"],
            df["totalDeputeBuy"] + df["totalDeputeSell"],
        )
    if "volume" in df:
        vol = df["volume"].replace(0, np.nan)
        df["log_volume"] = np.log1p(vol)
        df["volume_shock_20_120"] = df["volume"].rolling(20, min_periods=1).mean() / (df["volume"].rolling(120, min_periods=1).mean() + 1e-12)
        df["activity_surge_20_120"] = df["volume"].abs().rolling(20, min_periods=1).sum() / (df["volume"].abs().rolling(120, min_periods=1).mean() + 1e-12)
    return df