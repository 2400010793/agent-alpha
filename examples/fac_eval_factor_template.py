from __future__ import annotations

import pandas as pd


fields = ["alpha_depth_imbalance_l1"]


def compute_factor(code: str, date: str, df: pd.DataFrame) -> pd.DataFrame:
    """Minimal fac-eval compatible high-frequency factor template.

    This template uses only historical same-row order book fields. It does not
    reference forward label columns such as ret60s.
    """
    bid_v = pd.to_numeric(df["bidV1"], errors="coerce")
    ask_v = pd.to_numeric(df["askV1"], errors="coerce")
    alpha = (bid_v - ask_v) / (bid_v + ask_v + 1e-12)
    return pd.DataFrame({"alpha_depth_imbalance_l1": alpha})