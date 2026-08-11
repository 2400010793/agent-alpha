from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


EPS = 1e-12


def _op_args(node: Any) -> tuple[str, list[Any]]:
    if isinstance(node, list) and node:
        return str(node[0]), list(node[1:])
    if isinstance(node, dict):
        args = node.get("args", [])
        return str(node.get("op") or ""), list(args if isinstance(args, list) else [args])
    raise ValueError(f"invalid prefix node: {node!r}")


def _series(value: Any, index: pd.Index) -> pd.Series:
    if isinstance(value, pd.Series):
        return value
    if isinstance(value, np.ndarray):
        return pd.Series(value, index=index)
    return pd.Series(value, index=index)


def _add_basic_hf_features(features: pd.DataFrame) -> pd.DataFrame:
    if "askP1" in features and "bidP1" in features:
        ask_p1 = pd.to_numeric(features["askP1"], errors="coerce")
        bid_p1 = pd.to_numeric(features["bidP1"], errors="coerce")
        features["spread_l1"] = ask_p1 - bid_p1
        features["mid_price_l1"] = (ask_p1 + bid_p1) / 2.0
        features["relative_spread_l1"] = features["spread_l1"] / (features["mid_price_l1"] + EPS)
    if "askV1" in features and "bidV1" in features:
        ask_v1 = pd.to_numeric(features["askV1"], errors="coerce")
        bid_v1 = pd.to_numeric(features["bidV1"], errors="coerce")
        features["depth_imbalance_l1"] = (bid_v1 - ask_v1) / (bid_v1 + ask_v1 + EPS)
        if "askP1" in features and "bidP1" in features:
            ask_p1 = pd.to_numeric(features["askP1"], errors="coerce")
            bid_p1 = pd.to_numeric(features["bidP1"], errors="coerce")
            features["microprice_l1"] = (ask_p1 * bid_v1 + bid_p1 * ask_v1) / (ask_v1 + bid_v1 + EPS)
    if "volume" in features:
        volume = pd.to_numeric(features["volume"], errors="coerce")
        features["log_volume"] = np.log1p(volume.replace(0, np.nan))
        features["volume_shock_20_120"] = volume.rolling(20, min_periods=1).mean() / (volume.rolling(120, min_periods=1).mean() + EPS)
        features["activity_surge_20_120"] = volume.abs().rolling(20, min_periods=1).sum() / (volume.abs().rolling(120, min_periods=1).mean() + EPS)
    return features


def _eval_prefix(node: Any, features: pd.DataFrame) -> Any:
    if isinstance(node, str):
        if node not in features:
            raise ValueError(f"missing factor field: {node}")
        return pd.to_numeric(features[node], errors="coerce")
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return node
    op, args = _op_args(node)
    evaluate = lambda value: _eval_prefix(value, features)
    if op in {"add", "sub", "mul", "div"}:
        left, right = evaluate(args[0]), evaluate(args[1])
        return {"add": lambda: left + right, "sub": lambda: left - right, "mul": lambda: left * right, "div": lambda: left / right}[op]()
    if op == "safe_div":
        return evaluate(args[0]) / (evaluate(args[1]) + EPS)
    if op == "neg":
        return -evaluate(args[0])
    if op == "abs":
        return _series(evaluate(args[0]), features.index).abs()
    if op == "clip":
        return _series(evaluate(args[0]), features.index).clip(lower=float(args[1]), upper=float(args[2]))
    if op == "log1p":
        return np.log1p(evaluate(args[0]))
    if op == "log":
        return np.log(_series(evaluate(args[0]), features.index).abs() + EPS)
    if op == "tanh":
        return np.tanh(evaluate(args[0]))
    if op == "sign":
        return np.sign(evaluate(args[0]))
    if op == "rank":
        return _series(evaluate(args[0]), features.index).rank(pct=True)
    if op == "zscore":
        value = _series(evaluate(args[0]), features.index)
        window = int(args[1]) if len(args) > 1 else 60
        mean = value.rolling(window, min_periods=1).mean()
        std = value.rolling(window, min_periods=1).std().replace(0, np.nan)
        return (value - mean) / (std + EPS)
    rolling_methods = {
        "rolling_mean": "mean",
        "rolling_std": "std",
        "rolling_sum": "sum",
        "rolling_min": "min",
        "rolling_max": "max",
        "rolling_median": "median",
    }
    if op in rolling_methods:
        rolling = _series(evaluate(args[0]), features.index).rolling(int(args[1]), min_periods=1)
        return getattr(rolling, rolling_methods[op])()
    if op == "rolling_rank":
        return _series(evaluate(args[0]), features.index).rolling(int(args[1]), min_periods=1).apply(
            lambda values: pd.Series(values).rank(pct=True).iloc[-1], raw=False
        )
    if op == "rolling_count":
        return _series(evaluate(args[0]), features.index).astype(float).rolling(int(args[1]), min_periods=1).sum()
    if op in {"ewm_mean", "ewm_std"}:
        ewm = _series(evaluate(args[0]), features.index).ewm(halflife=int(args[1]), min_periods=1, adjust=True)
        return getattr(ewm, "mean" if op == "ewm_mean" else "std")()
    if op in {"diff", "shift", "pct_change"}:
        return getattr(_series(evaluate(args[0]), features.index), op)(int(args[1]))
    if op in {"max", "min"}:
        function = np.maximum if op == "max" else np.minimum
        return _series(function(evaluate(args[0]), evaluate(args[1])), features.index)
    comparisons = {"gt": "gt", "lt": "lt", "ge": "ge", "le": "le", "eq": "eq", "neq": "ne"}
    if op in comparisons:
        return getattr(_series(evaluate(args[0]), features.index), comparisons[op])(evaluate(args[1]))
    if op in {"and", "or"}:
        left = _series(evaluate(args[0]), features.index).astype(bool)
        right = _series(evaluate(args[1]), features.index).astype(bool)
        return left & right if op == "and" else left | right
    if op == "where":
        condition = _series(evaluate(args[0]), features.index).astype(bool)
        return pd.Series(np.where(condition, evaluate(args[1]), evaluate(args[2])), index=features.index)
    if op in {"rolling_corr", "rolling_cov"}:
        left = _series(evaluate(args[0]), features.index).rolling(int(args[2]), min_periods=2)
        right = _series(evaluate(args[1]), features.index)
        return getattr(left, "corr" if op == "rolling_corr" else "cov")(right)
    if op == "rolling_beta":
        y = _series(evaluate(args[0]), features.index)
        x = _series(evaluate(args[1]), features.index)
        window = int(args[2])
        return y.rolling(window, min_periods=2).cov(x) / (x.rolling(window, min_periods=2).var() + EPS)
    if op in {"div_mean", "div_std"}:
        ratio = _series(evaluate(args[0]) / (evaluate(args[1]) + EPS), features.index)
        rolling = ratio.rolling(int(args[2]), min_periods=1)
        return getattr(rolling, "mean" if op == "div_mean" else "std")()
    if op == "vol_scale":
        value = _series(evaluate(args[0]), features.index)
        return value / (value.rolling(int(args[1]), min_periods=1).std() + EPS)
    raise ValueError(f"unsupported local factor op: {op}")


def calculate_factor_values(candidate: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Evaluate the same controlled ASL used by the fac-eval renderer."""
    prefix = candidate.get("prefix_expression") if isinstance(candidate, dict) else None
    if prefix is None:
        raise ValueError("candidate must include prefix_expression for local calculation")
    source_rows = rows or []
    features = _add_basic_hf_features(pd.DataFrame(source_rows))
    values = _series(_eval_prefix(prefix, features), features.index)
    factor_id = str(candidate.get("factor_id") or candidate.get("name") or "")
    return [{"row_index": int(index), "factor_id": factor_id, "value": value} for index, value in values.items()]
