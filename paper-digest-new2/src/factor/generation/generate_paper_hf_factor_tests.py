#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]


HELPERS = dedent(
    '''
    from __future__ import annotations

    import numpy as np
    import pandas as pd

    inf = np.inf
    nan = np.nan


    def _num(df: pd.DataFrame, col: str) -> pd.Series:
        if col not in df.columns:
            return pd.Series(np.nan, index=df.index, dtype="float64")
        return pd.to_numeric(df[col], errors="coerce")


    def _sum_cols(df: pd.DataFrame, cols: list[str]) -> pd.Series:
        total = pd.Series(0.0, index=df.index, dtype="float64")
        for col in cols:
            total = total + _num(df, col)
        return total


    def _safe_div(numer: pd.Series, denom: pd.Series) -> pd.Series:
        denom = denom.replace(0, np.nan)
        return (numer / denom).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _rolling_mean(series: pd.Series, window: int) -> pd.Series:
        return series.rolling(window=max(1, int(window)), min_periods=1).mean()


    def _rolling_sum(series: pd.Series, window: int) -> pd.Series:
        return series.rolling(window=max(1, int(window)), min_periods=1).sum()


    def _rolling_std(series: pd.Series, window: int) -> pd.Series:
        return series.rolling(window=max(2, int(window)), min_periods=2).std().fillna(0.0)


    def _rolling_cov(left: pd.Series, right: pd.Series, window: int) -> pd.Series:
        return left.rolling(window=max(2, int(window)), min_periods=2).cov(right).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _rolling_corr(left: pd.Series, right: pd.Series, window: int) -> pd.Series:
        return left.rolling(window=max(2, int(window)), min_periods=2).corr(right).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _conditional_mean(target: pd.Series, condition: pd.Series, window: int) -> pd.Series:
        mask = condition > _rolling_mean(condition, window)
        selected = target.where(mask)
        fallback = _rolling_mean(target, window)
        return _rolling_mean(selected, window).fillna(fallback).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _rolling_beta(target: pd.Series, benchmark: pd.Series, window: int) -> pd.Series:
        return _safe_div(_rolling_cov(target, benchmark, window), _rolling_std(benchmark, window) ** 2 + 1e-6)


    def _rolling_integral(series: pd.Series, window: int) -> pd.Series:
        return _rolling_sum(series, window)


    def _ewm_integral(series: pd.Series, halflife: int) -> pd.Series:
        return series.ewm(halflife=max(1, int(halflife)), adjust=False, min_periods=1).mean().replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _ewma(series: pd.Series, alpha: float = 0.05) -> pd.Series:
        weight = min(1.0, max(1e-6, float(alpha)))
        return series.ewm(alpha=weight, adjust=False, min_periods=1).mean().replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _coherence(series: pd.Series, window: int = 20) -> pd.Series:
        signs = np.sign(series).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return _rolling_mean(signs, window)


    def _path_ratio(series: pd.Series, window: int = 20) -> pd.Series:
        horizon = max(1, int(window))
        displacement = (series - series.shift(horizon)).abs().fillna(0.0)
        path_length = _rolling_sum(_diff(series).abs(), horizon)
        return _safe_div(displacement, path_length.abs() + 1e-6)


    def _rolling_min(series: pd.Series, window: int) -> pd.Series:
        return series.rolling(window=max(1, int(window)), min_periods=1).min().replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _rolling_max(series: pd.Series, window: int) -> pd.Series:
        return series.rolling(window=max(1, int(window)), min_periods=1).max().replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _rolling_median(series: pd.Series, window: int) -> pd.Series:
        return series.rolling(window=max(1, int(window)), min_periods=1).median().replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _rolling_quantile(series: pd.Series, window: int, quantile: float) -> pd.Series:
        q = max(0.0, min(1.0, float(quantile)))
        return series.rolling(window=max(1, int(window)), min_periods=1).quantile(q).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _rolling_skew(series: pd.Series, window: int) -> pd.Series:
        return series.rolling(window=max(3, int(window)), min_periods=3).skew().replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _expanding_mean(series: pd.Series) -> pd.Series:
        return series.expanding(min_periods=1).mean().replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _expanding_min(series: pd.Series) -> pd.Series:
        return series.expanding(min_periods=1).min().replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _expanding_max(series: pd.Series) -> pd.Series:
        return series.expanding(min_periods=1).max().replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _cumsum(series: pd.Series) -> pd.Series:
        return series.cumsum().replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _rank(series: pd.Series) -> pd.Series:
        return series.rank(pct=True).replace([np.inf, -np.inf], np.nan).fillna(0.5)


    def _shift(series: pd.Series, periods: int = 1) -> pd.Series:
        return series.shift(int(periods)).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _pct_change(series: pd.Series, periods: int = 1) -> pd.Series:
        return series.pct_change(int(periods)).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _sign(series: pd.Series) -> pd.Series:
        return np.sign(series).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _first(series: pd.Series) -> pd.Series:
        first_valid = series.dropna().iloc[0] if not series.dropna().empty else np.nan
        return pd.Series(first_valid, index=series.index, dtype="float64").replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _session_open(df: pd.DataFrame) -> pd.Series:
        official_open = _num(df, "daily_open")
        fallback_open = _first(_num(df, "close"))
        return official_open.where(official_open > 0, fallback_open).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _zscore(series: pd.Series, window: object = 20) -> pd.Series:
        if isinstance(window, pd.Series):
            return _safe_div(series, window.replace(0, np.nan))
        mean = _rolling_mean(series, window)
        std = _rolling_std(series, window).replace(0, np.nan)
        return _safe_div(series - mean, std)


    def _log(series: pd.Series) -> pd.Series:
        return np.log(series.clip(lower=1e-12)).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _exp(series: pd.Series) -> pd.Series:
        return np.exp(series.clip(upper=20)).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _abs(series: pd.Series) -> pd.Series:
        return series.abs().replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _sqrt(series: pd.Series) -> pd.Series:
        return np.sqrt(series.clip(lower=0.0)).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _clip(series: pd.Series, lower: float, upper: float) -> pd.Series:
        return series.clip(lower=float(lower), upper=float(upper)).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _where(condition: pd.Series, left: pd.Series, right: pd.Series) -> pd.Series:
        return pd.Series(np.where(condition.fillna(False), left, right), index=left.index, dtype="float64").replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _mid_price(df: pd.DataFrame) -> pd.Series:
        return (_num(df, "askP1") + _num(df, "bidP1")) / 2.0


    def _mid_log_return(df: pd.DataFrame) -> pd.Series:
        mid = _mid_price(df)
        base = _num(df, "last_close").where(_num(df, "last_close") > 0, _num(df, "close").shift(1))
        return _log(_safe_div(mid, base))


    def _book_imbalance(df: pd.DataFrame, depth: int = 3) -> pd.Series:
        bid_cols = [f"bidV{i}" for i in range(1, depth + 1)]
        ask_cols = [f"askV{i}" for i in range(1, depth + 1)]
        bid_sum = _sum_cols(df, bid_cols)
        ask_sum = _sum_cols(df, ask_cols)
        return _safe_div(bid_sum - ask_sum, bid_sum + ask_sum + 1e-6)


    def _lob_pressure(df: pd.DataFrame, depth: int = 5, alpha: float = 0.5) -> pd.Series:
        """Distance-decayed visible LOB pressure, normalized to [-1, 1]."""
        levels = max(1, min(10, int(depth)))
        decay = max(0.0, float(alpha))
        best_bid = _num(df, "bidP1")
        best_ask = _num(df, "askP1")
        tick_scale = (_num(df, "askP1") - _num(df, "bidP1")).abs().clip(lower=1e-6)
        bid_pressure = pd.Series(0.0, index=df.index, dtype="float64")
        ask_pressure = pd.Series(0.0, index=df.index, dtype="float64")
        for level in range(1, levels + 1):
            bid_distance = (_num(df, f"bidP{level}") - best_bid).abs() / tick_scale
            ask_distance = (_num(df, f"askP{level}") - best_ask).abs() / tick_scale
            bid_pressure = bid_pressure + _safe_div(_num(df, f"bidV{level}"), 1.0 + decay * bid_distance)
            ask_pressure = ask_pressure + _safe_div(_num(df, f"askV{level}"), 1.0 + decay * ask_distance)
        return _safe_div(bid_pressure - ask_pressure, bid_pressure + ask_pressure + 1e-6)


    def _space_decay(level1: pd.Series, level2: pd.Series, level3: pd.Series, level4: pd.Series, level5: pd.Series, alpha: float = 0.5) -> pd.Series:
        """Exponentially decayed spatial aggregation of signed five-level pressure."""
        decay = max(0.0, float(alpha))
        weights = [1.0, np.exp(-decay), np.exp(-2.0 * decay), np.exp(-3.0 * decay), np.exp(-4.0 * decay)]
        levels = [level1, level2, level3, level4, level5]
        weighted = sum(weight * level for weight, level in zip(weights, levels))
        scale = sum(weight * level.abs() for weight, level in zip(weights, levels))
        return _safe_div(weighted, scale + 1e-6)


    def _exp_decay(series: pd.Series, halflife: int = 20) -> pd.Series:
        """Causal exponentially decayed convolution with a one-sided kernel."""
        return series.ewm(halflife=max(1, int(halflife)), adjust=False, min_periods=1).mean().replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _decayed_interaction(left: pd.Series, right: pd.Series, halflife: int = 20) -> pd.Series:
        """Causal exponential convolution of a two-signal interaction."""
        return _exp_decay(left * right, halflife)


    def _bid_depth(df: pd.DataFrame, depth: int = 5) -> pd.Series:
        return _sum_cols(df, [f"bidV{i}" for i in range(1, depth + 1)])


    def _ask_depth(df: pd.DataFrame, depth: int = 5) -> pd.Series:
        return _sum_cols(df, [f"askV{i}" for i in range(1, depth + 1)])


    def _spread(df: pd.DataFrame) -> pd.Series:
        return _safe_div(_num(df, "askP1") - _num(df, "bidP1"), _mid_price(df) + 1e-6)


    def _volume_weighted(series: pd.Series, volume: pd.Series, window: int) -> pd.Series:
        return _safe_div(_rolling_sum(series * volume, window), _rolling_sum(volume, window) + 1e-6)


    def _diff(series: pd.Series, periods: int = 1) -> pd.Series:
        return series.diff(max(1, int(periods))).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _lob_vector_zdistance(df: pd.DataFrame, depth: int = 10, window: int = 60) -> pd.Series:
        components = []
        for level in range(1, depth + 1):
            components.append(_zscore(_num(df, f"bidV{level}"), window) ** 2)
            components.append(_zscore(_num(df, f"askV{level}"), window) ** 2)
            components.append(_zscore(_diff(_num(df, f"bidP{level}")), window) ** 2)
            components.append(_zscore(_diff(_num(df, f"askP{level}")), window) ** 2)
        total = pd.Series(0.0, index=df.index, dtype="float64")
        for component in components:
            total = total + component
        return np.sqrt(total).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _microstructure_noise_trace(df: pd.DataFrame, window: int = 60) -> pd.Series:
        mid_return = _mid_log_return(df)
        spread_change = _diff(_spread(df))
        obi_change = _diff(_book_imbalance(df, 5))
        depth_change = _diff(_safe_div(_sum_cols(df, ["bidV1", "bidV2", "bidV3", "bidV4", "bidV5"]) + _sum_cols(df, ["askV1", "askV2", "askV3", "askV4", "askV5"]), _num(df, "volume") + 1e-6))
        return (
            _rolling_std(mid_return, window) ** 2
            + _rolling_std(spread_change, window) ** 2
            + _rolling_std(obi_change, window) ** 2
            + _rolling_std(depth_change, window) ** 2
        ).replace([np.inf, -np.inf], np.nan).fillna(0.0)


    def _cost_adjusted_score(signal: pd.Series, volatility: pd.Series, spread: pd.Series) -> pd.Series:
        return _safe_div(signal, volatility.abs() + spread.abs() + 1e-6)


    def _no_trade_band_distance(signal: pd.Series, cost: pd.Series, volatility: pd.Series) -> pd.Series:
        band = cost.abs() + 0.5 * volatility.abs()
        return (signal.abs() - band).clip(lower=0.0) * np.sign(signal)
    '''
).strip()


def _load_pipeline() -> Any:
    from src.pipeline import daily_research_pipeline

    return daily_research_pipeline


def _slug(value: str, limit: int = 34) -> str:
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", value.lower()).strip("_")
    return (slug or "paper_hf")[:limit]


def _canon_set(factor: dict[str, Any]) -> set[str]:
    return {str(item.get("canonical_variable")) for item in factor.get("proxy_mappings", []) if isinstance(item, dict)}


def _strengths(factor: dict[str, Any]) -> set[str]:
    return {str(item.get("proxy_strength")) for item in factor.get("proxy_mappings", []) if isinstance(item, dict)}


WEAK_AUTOGEN_CANONICALS = {
    "adverse_selection",
    "benchmark_return_series",
    "cluster_id",
    "inventory",
    "latent_regime",
    "predicted_probability",
    "signed_order_flow",
    "systematic_flow",
    "realized_volatility",
    "order_book_imbalance",
    "mid_price",
    "return_series",
    "execution_friction",
    "market_cap",
    "average_daily_volume",
    "order_flow_imbalance",
}
WEAK_BASE_ONLY_CANONICALS = {
    "benchmark_return_series",
    "cluster_id",
    "latent_regime",
    "predicted_probability",
    "systematic_flow",
}
ROBUST_MATRIX_TEMPLATE_HINTS = {
    "activity_surge",
    "execution_friction",
    "order_book_imbalance",
    "realized_volatility",
}
ABSTRACT_WEAK_AUTOGEN_FLAGS = {
    "abstract_diffusion_policy",
    "abstract_disclosure_impact",
    "abstract_execution_control",
    "abstract_prediction_market",
    "abstract_robust_portfolio",
    "abstract_transfer_entropy",
    "abstract_operator_volatility",
    "abstract_cfmm_amm",
    "abstract_tail_risk",
    "abstract_deep_hedging_uncertainty",
    "abstract_rl_forecast_residual",
}


DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "config" / "proxy_variant_templates.yaml"
ALLOWED_FORMULA_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CUSTOM_FORMULA_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CUSTOM_FORMULA_HELPERS = {
    "abs",
    "ask_depth",
    "bid_depth",
    "book_imbalance",
    "clip",
    "conditional_mean",
    "cost_adjusted_score",
    "coherence",
    "cumsum",
    "decayed_interaction",
    "diff",
    "ewm_integral",
    "ewma",
    "exp",
    "exp_decay",
    "expanding_max",
    "expanding_mean",
    "expanding_min",
    "first",
    "lob_vector_zdistance",
    "log",
    "lob_pressure",
    "mid_log_return",
    "mid_price",
    "microstructure_noise_trace",
    "no_trade_band_distance",
    "path_ratio",
    "pct_change",
    "rank",
    "rolling_beta",
    "rolling_corr",
    "rolling_cov",
    "rolling_integral",
    "rolling_max",
    "rolling_mean",
    "rolling_median",
    "rolling_min",
    "rolling_quantile",
    "rolling_skew",
    "rolling_std",
    "rolling_sum",
    "safe_div",
    "session_open",
    "shift",
    "sign",
    "spread",
    "space_decay",
    "sqrt",
    "volume_weighted",
    "where",
    "zscore",
}
CUSTOM_FORMULA_COMPLEX_HELPERS = {
    "clip",
    "conditional_mean",
    "cost_adjusted_score",
    "coherence",
    "decayed_interaction",
    "ewm_integral",
    "ewma",
    "exp",
    "exp_decay",
    "lob_vector_zdistance",
    "lob_pressure",
    "log",
    "microstructure_noise_trace",
    "no_trade_band_distance",
    "path_ratio",
    "pct_change",
    "rank",
    "rolling_beta",
    "rolling_corr",
    "rolling_cov",
    "rolling_integral",
    "rolling_max",
    "rolling_mean",
    "rolling_median",
    "rolling_min",
    "rolling_quantile",
    "rolling_skew",
    "rolling_std",
    "rolling_sum",
    "safe_div",
    "session_open",
    "shift",
    "sign",
    "space_decay",
    "sqrt",
    "volume_weighted",
    "where",
    "zscore",
}
CUSTOM_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)


def _load_template_config(path: Path = DEFAULT_TEMPLATE_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(payload, dict):
        raise ValueError(f"template config must be a mapping: {path}")
    operators = payload.get("operators", [])
    templates = payload.get("templates", [])
    if not isinstance(operators, list) or not isinstance(templates, list):
        raise ValueError(f"template config has invalid operators/templates: {path}")
    return payload


def _template_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in config.get("templates", []):
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = item
    return out


def _validate_template_formula(template: dict[str, Any], allowed_operators: set[str]) -> None:
    formula = str(template.get("formula") or "")
    if not formula:
        raise ValueError(f"template {template.get('id')} missing formula")
    allowed_names = allowed_operators | {"df", "np", "abs", "min", "max", "int", "float", "inf", "nan", "e", "sign"}
    for token in ALLOWED_FORMULA_TOKEN_RE.findall(formula):
        if token in allowed_names or token.startswith("ask") or token.startswith("bid"):
            continue
        if token in {"close", "volume", "money", "last_close", "daily_open"}:
            continue
        if re.fullmatch(r"V\d+|P\d+", token):
            continue
        raise ValueError(f"template {template.get('id')} uses non-whitelisted token: {token}")


def _custom_helper_name(name: str) -> str:
    return name[1:] if name.startswith("_") else name


def _best_executable_proxy_expression(mapping: dict[str, Any], pipeline: Any) -> str:
    candidates: list[str] = []
    raw_proxies = mapping.get("local_proxies")
    if isinstance(raw_proxies, list):
        for raw_proxy in raw_proxies:
            if not isinstance(raw_proxy, dict):
                continue
            if raw_proxy.get("validation_status") and raw_proxy.get("validation_status") != "executable":
                continue
            expression = str(raw_proxy.get("expression") or "").strip()
            if expression:
                candidates.append(expression)
    local_proxy = str(mapping.get("local_proxy") or "").strip()
    if local_proxy:
        candidates.append(local_proxy)
    for expression in candidates:
        compiled = pipeline._compile_llm_expression(expression)
        if compiled:
            return compiled
    return ""


def _custom_proxy_expression_map(factor: dict[str, Any], pipeline: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    plan = factor.get("paper_hf_formula_plan")
    if isinstance(plan, dict):
        declared = plan.get("proxy_variable_keys") or plan.get("used_proxy_variables") or []
        if isinstance(declared, list):
            for raw_name in declared:
                canonical = str(raw_name or "").strip()
                if not canonical or not CUSTOM_FORMULA_NAME_RE.fullmatch(canonical):
                    continue
                try:
                    mapping = pipeline._proxy_mapping_from_registry(canonical, canonical)
                except Exception:
                    continue
                compiled = _best_executable_proxy_expression(mapping, pipeline)
                if compiled:
                    out[canonical] = compiled
    mappings = factor.get("proxy_mappings")
    if not isinstance(mappings, list):
        return out
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        canonical = str(mapping.get("canonical_variable") or "").strip()
        if not canonical or not CUSTOM_FORMULA_NAME_RE.fullmatch(canonical):
            continue
        strength = str(mapping.get("proxy_strength") or "")
        if strength not in {"direct", "derived", "weak_proxy"}:
            continue
        compiled = _best_executable_proxy_expression(mapping, pipeline)
        if compiled:
            out[canonical] = compiled
    return out


def _validate_custom_formula_ast(tree: ast.Expression, proxy_names: set[str]) -> set[str]:
    if len(list(ast.walk(tree))) > 120:
        raise ValueError("custom_formula AST too large")
    used_proxy_names: set[str] = set()
    helper_calls: set[str] = set()
    has_condition = False
    max_depth = 0

    def visit(node: ast.AST, depth: int = 0) -> None:
        nonlocal has_condition, max_depth
        max_depth = max(max_depth, depth)
        if max_depth > 18:
            raise ValueError("custom_formula AST too deep")
        if not isinstance(node, CUSTOM_ALLOWED_AST_NODES):
            raise ValueError(f"custom_formula uses disallowed syntax: {type(node).__name__}")
        if isinstance(node, ast.Name):
            if node.id in proxy_names:
                used_proxy_names.add(node.id)
            elif _custom_helper_name(node.id) in CUSTOM_FORMULA_HELPERS:
                pass
            elif node.id in {"True", "False"}:
                pass
            else:
                raise ValueError(f"custom_formula uses unknown name: {node.id}")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("custom_formula calls must use helper names")
            helper = _custom_helper_name(node.func.id)
            if helper not in CUSTOM_FORMULA_HELPERS:
                raise ValueError(f"custom_formula calls disallowed helper: {node.func.id}")
            if node.keywords:
                raise ValueError("custom_formula helper calls must not use keyword arguments")
            helper_calls.add(helper)
        elif isinstance(node, ast.Compare):
            has_condition = True
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                if abs(float(node.value)) > 1000000:
                    raise ValueError("custom_formula numeric constant too large")
            elif node.value is not None:
                raise ValueError("custom_formula constants must be numeric")
        for child in ast.iter_child_nodes(node):
            visit(child, depth + 1)

    visit(tree)
    if len(used_proxy_names) < 1:
        raise ValueError("custom_formula must use at least 1 distinct proxy variable")
    return used_proxy_names


class _CustomFormulaTransformer(ast.NodeTransformer):
    def __init__(self, proxy_exprs: dict[str, str]) -> None:
        self.proxy_exprs = proxy_exprs
        self.placeholders: dict[str, str] = {}

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in self.proxy_exprs:
            placeholder = f"__custom_proxy_{len(self.placeholders)}__"
            self.placeholders[placeholder] = self.proxy_exprs[node.id]
            return ast.copy_location(ast.Name(id=placeholder, ctx=node.ctx), node)
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name):
            helper = _custom_helper_name(node.func.id)
            if helper in CUSTOM_FORMULA_HELPERS:
                node.func.id = f"_{helper}"
        return node


def _prefix_to_python(formula: str) -> str:
    """Recursively converts S-expression (prefix notation) to Python expression."""
    formula = formula.replace("(", " ( ").replace(")", " ) ")
    tokens = [t for t in formula.split() if t]

    def parse(tokens: list[str]) -> str:
        if not tokens:
            raise ValueError("Unexpected end of formula")
        token = tokens.pop(0)
        if token == "(":
            if not tokens:
                raise ValueError("Incomplete S-expression")
            op = tokens.pop(0)
            args = []
            while tokens and tokens[0] != ")":
                args.append(parse(tokens))
            if not tokens:
                raise ValueError("Missing ')'")
            tokens.pop(0)  # consume ')'

            # Binary Operators and Comparisons
            if op in {"+", "-", "*", "/", "**", ">", "<", ">=", "<=", "==", "!="}:
                if len(args) == 2:
                    return f"({args[0]} {op} {args[1]})"
                if op == "-" and len(args) == 1:
                    return f"-({args[0]})"
                raise ValueError(f"Operator {op} requires 2 arguments, got {len(args)}")

            # Helper Functions
            return f"{op}({', '.join(args)})"
        return token

    return parse(tokens)


def _translate_custom_formula(factor: dict[str, Any], pipeline: Any | None = None) -> str:
    plan = factor.get("paper_hf_formula_plan")
    if not isinstance(plan, dict):
        raise ValueError("missing paper_hf_formula_plan")
    prefix_formula = str(plan.get("custom_formula_prefix") or plan.get("prefix_formula") or "").strip()
    formula = prefix_formula or str(plan.get("custom_formula") or "").strip()
    if not formula:
        raise ValueError("missing custom_formula")
    if len(formula) > 1500:
        raise ValueError("custom_formula too long")

    if formula.startswith("("):
        try:
            formula = _prefix_to_python(formula)
        except Exception as exc:
            raise ValueError(f"S-expression translation error: {exc}") from exc


    if re.search(r"[^0-9A-Za-z_\s\+\-\*/%\.\(\),<>=!&|]", formula):
        raise ValueError("custom_formula contains unsupported characters")
    pipeline = pipeline or _load_pipeline()
    proxy_exprs = _custom_proxy_expression_map(factor, pipeline)
    if len(proxy_exprs) < 1:
        raise ValueError("factor has no executable proxy variables")
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"custom_formula syntax error: {exc}") from exc
    used_proxy_names = _validate_custom_formula_ast(tree, set(proxy_exprs))
    declared = plan.get("used_proxy_variables") or plan.get("proxy_variable_keys") or []
    if isinstance(declared, list):
        declared_names = {str(item) for item in declared if str(item)}
        if declared_names and used_proxy_names != declared_names:
            raise ValueError("custom_formula used variables do not match declared proxy variables")
    transformer = _CustomFormulaTransformer({name: proxy_exprs[name] for name in used_proxy_names})
    transformed = transformer.visit(tree)
    ast.fix_missing_locations(transformed)
    rendered = ast.unparse(transformed)
    for placeholder, expression in transformer.placeholders.items():
        rendered = re.sub(rf"\b{re.escape(placeholder)}\b", f"({expression})", rendered)
    ast.parse(rendered, mode="eval")
    return rendered


def _custom_formula_complexity(formula: str) -> tuple[int, int]:
    text = formula.strip()
    if text.startswith("("):
        tokens = [token for token in text.replace("(", " ( ").replace(")", " ) ").split() if token]

        def parse(position: int = 0) -> tuple[int, int, int]:
            if position >= len(tokens):
                raise ValueError("unexpected end")
            if tokens[position] != "(":
                return position + 1, 0, 0
            position += 2
            count = 1
            depth = 1
            while position < len(tokens) and tokens[position] != ")":
                position, child_count, child_depth = parse(position)
                count += child_count
                if child_depth:
                    depth = max(depth, child_depth + 1)
            if position >= len(tokens):
                raise ValueError("missing close paren")
            return position + 1, count, depth

        try:
            end, count, depth = parse(0)
        except ValueError:
            return 0, 0
        return (count, depth) if end == len(tokens) else (0, 0)
    operation_count = len(re.findall(r"[+\-*/]", text)) + len(re.findall(r"\b(?:zscore|rolling|mean|std|corr|cov|beta|sum|log|abs|sqrt|clip|conditional_mean)\s*\(", text, re.I))
    depth = 0
    max_depth = 0
    for char in text:
        if char == "(":
            depth += 1
            max_depth = max(max_depth, depth)
        elif char == ")":
            depth = max(depth - 1, 0)
    return operation_count, max_depth


def _custom_formula_is_complex(formula: str) -> bool:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", formula.strip()):
        return False
    operation_count, depth = _custom_formula_complexity(formula)
    return operation_count >= 3 and depth >= 3


def _formula_plan_template_ids(factor: dict[str, Any], template_ids: set[str]) -> list[str]:
    plan = factor.get("paper_hf_formula_plan")
    if not isinstance(plan, dict):
        return []
    raw_templates = plan.get("templates") or plan.get("template_ids") or plan.get("preferred_templates") or []
    for key in ("template_id", "fallback_template"):
        if plan.get(key):
            raw_templates = [plan.get(key), *raw_templates] if isinstance(raw_templates, list) else [plan.get(key), raw_templates]
    if isinstance(raw_templates, str):
        raw_templates = [raw_templates]
    if not isinstance(raw_templates, list):
        return []
    return [str(item) for item in raw_templates if str(item) in template_ids]


def _factor_flags(factor: dict[str, Any]) -> set[str]:
    canon = _canon_set(factor)
    strengths = _strengths(factor)
    text = " ".join(str(factor.get(key, "")) for key in ("name", "mechanism_formula", "meaning", "paper_mechanism")).lower()
    mechanism_type = str(factor.get("mechanism_type") or "").lower()
    flags: set[str] = set()

    def add(flag: str, condition: bool) -> None:
        if condition:
            flags.add(flag)

    add("no_proxy_mappings", not strengths)
    add("lob_vector_divergence", "lob_vector_divergence" in mechanism_type or "vector divergence" in text or "lod" in text or "散度" in text)
    add("microstructure_noise_covariance", "microstructure_noise_covariance" in mechanism_type or "covariance" in text or "协方差" in text or "second-order" in text or "二阶" in text)
    add("return", bool(canon & {"return_series", "trade_price"}) or "return" in text or "momentum" in text or "reversal" in text or "acceleration" in text or "path efficiency" in text or "breakout" in text or "回报" in text or "收益" in text or "动量" in text or "反转" in text)
    add("volume", bool(canon & {"volume_or_trade_activity", "order_size"}) or "volume" in text or "成交量" in text or "turnover" in text)
    add("obi", "order_book_imbalance" in canon or "obi" in text or "order-flow" in text or "order flow" in text or "order book" in text or "book imbalance" in text or "book asymmetry" in text or "lob asymmetry" in text or "depth asymmetry" in text or "盘口" in text or "不对称" in text or "簿" in text)
    add("spread", "execution_friction" in canon or "spread" in text or "价差" in text)
    add("volatility", "realized_volatility" in canon or "volatility" in text or "波动" in text)
    add("signed_flow", "signed_order_flow" in canon or "signed flow" in text or "signed order" in text or "订单流" in text or "交易符号" in text)
    add("notional_flow", "signed_notional_flow" in canon or "money flow" in text or "notional" in text or "成交额" in text or "资金流" in text)
    add("trade_event", "trade_event_intensity" in canon or "event count" in text or "trade count" in text or "counting process" in text or "事件强度" in text)
    add("order_size", "order_size" in canon or "order size" in text or "trade size" in text or "成交规模" in text)
    add("queue_change", "queue_change" in canon or "queue change" in text or "depth change" in text or "queue velocity" in text or "imbalance velocity" in text or "book velocity" in text or "asymmetry velocity" in text or "队列变化" in text)
    add("replenishment", "depth_replenishment" in canon or "replenishment" in text or "posted volume" in text or "liquidity supply" in text or "补单" in text)
    add("depletion", "unexplained_depth_depletion" in canon or "cancellation" in text or "cancel" in text or "depth depletion" in text or "撤单" in text)
    add("candlestick", "candlestick_geometry" in canon or "candlestick" in text or "candle" in text or "ohlc" in text or "wick" in text or "shadow" in text)
    add("session_open", "session_open_price" in canon or "session open" in text or "open price" in text or "opening price" in text)
    add("online_vwap", "online_vwap_twap" in canon or "vwap" in text or "twap" in text or "volume weighted average price" in text)
    add("online_range", "online_intraday_range" in canon or "range position" in text or "high so far" in text or "low so far" in text or "intraday range" in text or "drawdown" in text)
    add("inventory", "inventory" in canon or "inventory" in text or "库存" in text)
    add("adverse_selection", "adverse_selection" in canon or "adverse selection" in text or "逆选择" in text or "毒性" in text)
    add("benchmark", "benchmark_return_series" in canon or "benchmark" in text or "market return" in text or "index return" in text or "residual" in text or "市场收益" in text or "残差" in text)
    add("systematic_flow", "systematic_flow" in canon or "systematic flow" in text or "common flow" in text or "market-wide" in text or "market wide" in text or "系统性" in text or "共性" in text)
    add("latent_regime", "latent_regime" in canon or "latent regime" in text or "hidden state" in text or "hmm" in text or "regime" in text or "状态" in text)
    add("predicted_probability", "predicted_probability" in canon or "predicted probability" in text or "forecast probability" in text or "model forecast" in text or "概率" in text)
    add("cluster", "cluster_id" in canon or "cluster" in text or "archetype" in text or "聚类" in text)
    add("efficient_price", "efficient_price" in canon or "efficient price" in text or "fair value" in text or "microprice" in text or "有效价格" in text)
    add("noise_scale", "noise_scale" in canon or "microstructure noise" in text or "noise" in text or "噪声" in text)
    add("lob_state", "lob_state_divergence" in canon or "lob" in text or "depth pressure" in text or "book pressure" in text or "depth-weighted" in text or "depth weighted" in text or "depth shape" in text or "book shape" in text or "convexity" in text or "深度" in text or "盘口" in text or "形状" in text or "不对称" in text)
    add("conditional_expectation", "conditional expectation" in text or "conditional mean" in text or "conditioned mean" in text or "e[" in text or "e(" in text or "条件期望" in text or "条件均值" in text)
    if "conditional_expectation" in flags and "order_book_imbalance" in canon:
        flags.add("obi")
    if "conditional_expectation" in flags and "execution_friction" in canon:
        flags.add("spread")
    if "conditional_expectation" in flags:
        flags.add("return")
    add("cross_market_edge", "cross-market" in text or "cross market" in text or "bipartite" in text or "graph" in text or "edge" in text or "t_stat" in text or "跨市场" in text or "边强度" in text)
    add("self_exciting", "self-exciting" in text or "self exciting" in text or "hawkes" in text or "rough" in text or "long-memory" in text or "long memory" in text or "fractional" in text or "自激" in text or "长程记忆" in text or "粗糙" in text)
    add("robust_optimization", "argmin" in text or "minimum variance" in text or "min-variance" in text or "mean-variance" in text or "cvar" in text or "qubo" in text or "optimal rebalancing" in text or "最小方差" in text or "鲁棒组合" in text or "最优再平衡" in text)
    add("abstract_diffusion_policy", "diffusion" in text or "cvar" in text or "扩散" in text or "条件收益场景" in text)
    add("abstract_disclosure_impact", "disclosure" in text or "oligopolistic" in text or "披露" in text or "信息不对称" in text)
    add("abstract_execution_control", "optimal execution" in text or "model predictive control" in text or "mpc" in text or "execution rate" in text or "最优执行" in text or "最优切片" in text or "执行率" in text)
    add("abstract_prediction_market", "prediction market" in text or "implied probability" in text or "belief" in text or "parlay" in text or "预测市场" in text or "隐含概率" in text or "信念" in text)
    add("abstract_robust_portfolio", "argmin" in text or "robust portfolio" in text or "minimum variance" in text or "qubo" in text or "uncorrelated asset" in text or "ledoitwolf" in text or "最小方差" in text or "鲁棒组合" in text or "去相关" in text)
    add("abstract_transfer_entropy", "transfer entropy" in text or "entropy network" in text or "转移熵" in text)
    add("abstract_operator_volatility", "operator-level arch" in text or "operator arch" in text or "operator volatility" in text or "算子条件波动" in text or "算子" in text)
    add("abstract_cfmm_amm", "cfmm" in text or "constant function market making" in text or "automated market maker" in text or "amm" in text or "impermanent loss" in text or "无常损失" in text)
    add("abstract_tail_risk", "extreme value" in text or "tail risk" in text or "joint tail" in text or "尾部风险" in text or "极值" in text)
    add("abstract_deep_hedging_uncertainty", "deep hedging" in text or "ensemble" in text or "uncertainty" in text or "集成分歧" in text or "置信度" in text)
    add("abstract_rl_forecast_residual", "reinforcement learning" in text or "forecast residual" in text or "prediction residual" in text or "预测残差" in text or "日内预测" in text)
    return flags


def _template_matches(template: dict[str, Any], flags: set[str], canon: set[str]) -> bool:
    requires = {str(item) for item in template.get("requires_flags", []) if str(item)}
    if requires and not requires <= flags:
        return False
    any_flags = {str(item) for item in template.get("requires_any_flag", []) if str(item)}
    if any_flags and not flags & any_flags:
        return False
    excludes = {str(item) for item in template.get("excludes_flags", []) if str(item)}
    if excludes and flags & excludes:
        return False
    fallback = str(template.get("fallback_canonical") or "")
    if fallback and fallback not in canon:
        return False
    return bool(requires or any_flags or fallback)


FIDELITY_RANK = {
    "high": 5,
    "medium_high": 4,
    "medium": 3,
    "low_medium": 2,
    "low": 1,
}


def _template_family(template_id: str) -> str:
    text = str(template_id or "")
    for suffix in ("_shadow", "_proxy"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    if text.startswith("paper_hf_lob_asymmetry_"):
        return text
    parts = text.split("_")
    if len(parts) >= 4 and parts[0] == "paper" and parts[1] == "hf":
        return "_".join(parts[:4])
    return text


def _formula_operator_complexity(formula: str) -> int:
    helper_calls = len(re.findall(r"\b_[A-Za-z0-9_]+\s*\(", formula))
    binary_ops = len(re.findall(r"[+\-*/]", formula))
    advanced_bonus = 0
    for name in (
        "_rolling_cov",
        "_rolling_corr",
        "_rolling_beta",
        "_conditional_mean",
        "_rolling_integral",
        "_diff",
        "_microstructure_noise_trace",
        "_lob_vector_zdistance",
        "_lob_pressure",
        "_decayed_interaction",
        "_cost_adjusted_score",
        "_no_trade_band_distance",
    ):
        if name in formula:
            advanced_bonus += 4
    return helper_calls + binary_ops + advanced_bonus


def _template_priority_score(template: dict[str, Any]) -> tuple[int, int, int, int]:
    fidelity = FIDELITY_RANK.get(str(template.get("proxy_fidelity") or ""), 0)
    complexity = _formula_operator_complexity(str(template.get("formula") or ""))
    priority = -int(template.get("priority") or 100)
    base_penalty = -1 if template.get("base_only") or str(template.get("id") or "").endswith("_shadow") else 0
    return fidelity, complexity, priority, base_penalty


def _select_templates_by_family(candidates: list[dict[str, Any]], max_per_family: int = 2) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for template in candidates:
        template_id = str(template.get("id") or "")
        grouped.setdefault(_template_family(template_id), []).append(template)
    selected: list[dict[str, Any]] = []
    for family in sorted(grouped):
        ranked = sorted(grouped[family], key=_template_priority_score, reverse=True)
        selected.extend(ranked[:max_per_family])
    return sorted(selected, key=lambda item: (-_template_priority_score(item)[0], -_template_priority_score(item)[1], int(item.get("priority") or 100), str(item.get("id") or "")))


def _eligible_for_generation(factor: dict[str, Any]) -> bool:
    strengths = _strengths(factor)
    if not strengths and _factor_flags(factor) & ABSTRACT_WEAK_AUTOGEN_FLAGS:
        return True
    if not strengths:
        return False
    if strengths <= {"direct", "derived"}:
        return True
    if strengths <= {"direct", "derived", "weak_proxy"}:
        return True
    return False


def _generation_scope(factor: dict[str, Any]) -> str:
    plan = factor.get("paper_hf_formula_plan")
    return "full_variants" if isinstance(plan, dict) and str(plan.get("custom_formula") or "").strip() else "skip"


def _legacy_generation_scope(factor: dict[str, Any]) -> str:
    plan = factor.get("paper_hf_formula_plan")
    if isinstance(plan, dict) and plan.get("custom_formula"):
        return "full_variants"
    strengths = _strengths(factor)
    if not strengths and _factor_flags(factor) & ABSTRACT_WEAK_AUTOGEN_FLAGS:
        return "partial_base_only"
    if not _eligible_for_generation(factor):
        local_strengths = strengths & {"direct", "derived"}
        if local_strengths and "unsupported" not in strengths:
            return "partial_base_only"
        return "skip"
    return "full_variants"


def _field_name(row_title: str, factor: dict[str, Any], template: str) -> str:
    raw = f"{row_title}_{factor.get('name', '')}_{template}"
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"phf_{_slug(str(factor.get('name') or row_title), 28)}_{digest}"


def _variant_forms(variant: dict[str, str], template_config: dict[str, Any]) -> list[dict[str, str]]:
    formula = variant["formula"]
    template = variant["template"]
    form_config = template_config.get("variant_forms", {}) if isinstance(template_config.get("variant_forms"), dict) else {}
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def window_list(key: str, fallback: int) -> list[int]:
        raw = form_config.get(key)
        if raw is None:
            return [fallback]
        if isinstance(raw, int):
            return [raw]
        if isinstance(raw, list):
            values: list[int] = []
            for item in raw:
                try:
                    value = int(item)
                except (TypeError, ValueError):
                    continue
                if value > 0 and value not in values:
                    values.append(value)
            return values
        return [fallback]

    def add(suffix: str, expression: str, transform: str, loss_note: str) -> None:
        if expression in seen:
            return
        seen.add(expression)
        next_variant = dict(variant)
        next_variant["template"] = f"{template}_{suffix}"
        next_variant["formula"] = expression
        next_variant["variant_transform"] = transform
        next_variant["proxy_loss"] = f"{variant.get('proxy_loss', '')} {loss_note}".strip()
        out.append(next_variant)

    if form_config.get("base", True):
        add("base", formula, "base", "")
    if form_config.get("flip", True):
        add("flip", f"-({formula})", "direction_flip", "Direction-flip variant tests whether the mechanism is useful with inverted sign.")
    if form_config.get("rolling_mean_zscore", True):
        norm_window = window_list("rolling_mean_zscore_norm_windows", 60)[0]
        for window in window_list("rolling_mean_zscore_windows", 20):
            add(f"roll{window}", f"_zscore(_rolling_mean(({formula}), {window}), {norm_window})", f"rolling_window_{window}", "Rolling-window variant smooths local noise before testing IC.")
    deferred_zscore_windows: list[int] = []
    if form_config.get("zscore_120", True):
        zscore_windows = window_list("zscore_windows", 120)
        first_windows = [120] if 120 in zscore_windows else zscore_windows[:1]
        deferred_zscore_windows = [window for window in zscore_windows if window not in first_windows]
        for window in first_windows:
            add(f"z{window}", f"_zscore(({formula}), {window})", f"zscore_{window}", "Long-window zscore variant tests slower normalization.")
    if form_config.get("normalized_60", True):
        for window in window_list("normalized_windows", 60):
            add(f"norm{window}", f"_safe_div(({formula}), abs(_rolling_mean(({formula}), {window})) + 1e-6)", f"normalized_{window}", "Normalized variant scales by rolling absolute level.")
    for window in deferred_zscore_windows:
        add(f"z{window}", f"_zscore(({formula}), {window})", f"zscore_{window}", "Alternative-window zscore variant tests normalization horizon selection.")
    if form_config.get("depth_overrides", True) and "_book_imbalance(df," in formula:
        add("l1", re.sub(r"_book_imbalance\(df,\s*\d+\)", "_book_imbalance(df, 1)", formula), "L1_depth", "L1 variant uses top-of-book depth only.")
        add("l5", re.sub(r"_book_imbalance\(df,\s*\d+\)", "_book_imbalance(df, 5)", formula), "L5_depth", "L5 variant uses five-level visible depth.")
    if form_config.get("depth_overrides", True) and "_lob_vector_zdistance(df," in formula:
        add("l5", re.sub(r"_lob_vector_zdistance\(df,\s*\d+,", "_lob_vector_zdistance(df, 5,", formula), "L5_depth", "L5 vector variant reduces depth while preserving LOB geometry.")
        add("l10", re.sub(r"_lob_vector_zdistance\(df,\s*\d+,", "_lob_vector_zdistance(df, 10,", formula), "L10_depth", "L10 vector variant uses deeper visible book state.")
    return out


def _render_variants(factor: dict[str, Any], template_config: dict[str, Any], pipeline: Any | None = None) -> list[dict[str, str]]:
    canon = _canon_set(factor)
    flags = _factor_flags(factor)
    templates = _template_map(template_config)
    allowed_operators = {str(item) for item in template_config.get("operators", [])}
    selected_ids = _formula_plan_template_ids(factor, set(templates))
    raw_templates = [item for item in template_config.get("templates", []) if isinstance(item, dict)]

    candidates: list[dict[str, Any]] = []
    if selected_ids:
        for template_id in selected_ids:
            template = templates.get(template_id)
            if template and _template_matches(template, flags, canon):
                candidates.append(template)
    for template in raw_templates:
        if template in candidates:
            continue
        if _template_matches(template, flags, canon):
            candidates.append(template)

    variants: list[dict[str, str]] = []
    plan = factor.get("paper_hf_formula_plan")
    formula_source = "python_parsed_formula"
    if isinstance(plan, dict):
        formula_source = str(
            plan.get("formula_source")
            or ("llm_bulk_composite" if plan.get("synthesis_agent") == "bulk-composite-v1" else "python_parsed_formula")
        )
    if isinstance(plan, dict) and plan.get("custom_formula"):
        try:
            custom_formula = str(plan.get("custom_formula") or "")
            custom_complexity = _custom_formula_complexity(custom_formula)
            custom_is_complex = custom_complexity[0] >= 3 and custom_complexity[1] >= 3
            variants.append(
                {
                    "template": "bulk_custom_composite",
                    "formula": _translate_custom_formula(factor, pipeline),
                    "formula_source": formula_source,
                    "proxy_fidelity": "medium" if custom_is_complex else "low_medium",
                    "proxy_loss": str(plan.get("custom_formula_rationale") or plan.get("rationale") or "Bulk LLM composite proxy formula validated by AST whitelist."),
                    "variant_transform": "bulk_custom_formula",
                    "base_only": not custom_is_complex,
                    "weak_custom_formula": not custom_is_complex,
                    "custom_formula_complexity": custom_complexity,
                    "custom_formula_validation_status": "ok",
                }
            )
        except ValueError as exc:
            factor.setdefault("paper_hf_formula_plan", {})["validation_status"] = "rejected"
            factor.setdefault("paper_hf_formula_plan", {})["validation_error"] = str(exc)[:260]
            return []

    candidates = _select_templates_by_family(candidates)
    seen_templates: set[str] = set()
    stop_after_match = False
    for template in sorted(candidates, key=lambda item: int(item.get("priority") or 100)):
        template_id = str(template.get("id") or "")
        if not template_id or template_id in seen_templates:
            continue
        _validate_template_formula(template, allowed_operators)
        seen_templates.add(template_id)
        variants.append(
            {
                "template": template_id,
                "formula": str(template.get("formula") or ""),
                "formula_source": formula_source,
                "proxy_fidelity": str(template.get("proxy_fidelity") or "medium"),
                "proxy_loss": str(template.get("proxy_loss") or ""),
                "base_only": bool(template.get("base_only")),
            }
        )
        stop_after_match = stop_after_match or bool(template.get("stop_after_match"))
    if stop_after_match:
        return [variant for variant in variants if variant["template"] == "bulk_custom_composite" or templates.get(variant["template"], {}).get("stop_after_match")]
    return variants


def _iter_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def build_factor_specs(input_path: Path, limit: int, template_path: Path = DEFAULT_TEMPLATE_PATH) -> list[dict[str, Any]]:
    pipeline = _load_pipeline()
    template_config = _load_template_config(template_path)
    specs: list[dict[str, Any]] = []
    seen_fields: set[str] = set()
    for row_index, row in enumerate(_iter_rows(input_path)):
        title = str(row.get("title") or f"row_{row_index}")
        raw_factors = row.get("paper_hf_factors") or row.get("hf_factor_points", [])
        factors = pipeline.attach_paper_factor_proxy_analysis(
            pipeline.normalize_paper_hf_factors(raw_factors)
        )
        for factor_index, factor in enumerate(factors):
            generation_scope = _generation_scope(factor)
            if generation_scope == "skip":
                continue
            variants = _render_variants(factor, template_config, pipeline)
            if not variants:
                continue
            expanded_variants: list[dict[str, str]] = []
            for variant in variants:
                if generation_scope == "partial_base_only" or variant.get("base_only"):
                    base_variant = dict(variant)
                    base_variant["variant_transform"] = "partial_base"
                    base_variant["proxy_loss"] = f"{base_variant.get('proxy_loss', '')} Partial local proxy: external/future-pipeline variables are omitted; use only for coverage triage before full validation.".strip()
                    expanded_variants.append(base_variant)
                else:
                    expanded_variants.extend(_variant_forms(variant, template_config))
            for variant_index, variant in enumerate(expanded_variants):
                template = variant["template"]
                field = _field_name(title, {**factor, "name": f"{factor.get('name', '')}_{variant_index}"}, template)
                if field in seen_fields:
                    continue
                seen_fields.add(field)
                specs.append(
                    {
                        "field": field,
                        "formula": variant["formula"],
                        "template": template,
                        "proxy_fidelity": variant.get("proxy_fidelity", "medium"),
                        "proxy_loss": variant.get("proxy_loss", ""),
                        "variant_transform": variant.get("variant_transform", "base"),
                        "formula_source": variant.get("formula_source", "python_template"),
                        "generation_scope": generation_scope,
                        "base_only": bool(variant.get("base_only")),
                        "row_title": title,
                        "row_url": row.get("url", ""),
                        "paper_hf_factor_index": factor_index,
                        "variant_index": variant_index,
                        "paper_hf_factor": factor,
                        "canonical_variables": sorted(_canon_set(factor)),
                    }
                )
                if 0 < limit <= len(specs):
                    return specs
    return specs


def render_factor_file(specs: list[dict[str, Any]], template_path: Path = DEFAULT_TEMPLATE_PATH) -> str:
    fields = [spec["field"] for spec in specs]
    metadata = {
        "dedup_key": "paper_hf_direct_proxy_tests",
        "source": "paper_hf_factors",
        "generation_method": "paper_hf_factor_proxy_render_v1",
        "template_config": str(template_path),
        "factor_count": len(specs),
        "factors": [
            {
                "field": spec["field"],
                "template": spec["template"],
                "proxy_fidelity": spec.get("proxy_fidelity"),
                "proxy_loss": spec.get("proxy_loss"),
                "variant_transform": spec.get("variant_transform", "base"),
                "formula_source": spec.get("formula_source", "python_template"),
                "base_only": spec.get("base_only", False),
                "row_title": spec["row_title"],
                "row_url": spec["row_url"],
                "paper_hf_factor_index": spec["paper_hf_factor_index"],
                "variant_index": spec.get("variant_index", 0),
                "paper_hf_factor_name": spec["paper_hf_factor"].get("name"),
                "paper_hf_mechanism_formula": spec["paper_hf_factor"].get("mechanism_formula"),
                "paper_hf_mechanism_type": spec["paper_hf_factor"].get("mechanism_type"),
                "novelty_reason": spec["paper_hf_factor"].get("novelty_reason"),
                "classic_baseline": spec["paper_hf_factor"].get("classic_baseline"),
                "canonical_variables": spec["canonical_variables"],
                "proxy_status": spec["paper_hf_factor"].get("proxy_status"),
            }
            for spec in specs
        ],
    }
    assignments = "\n".join(
        f'    out[{json.dumps(spec["field"])}] = ({spec["formula"]}).replace([np.inf, -np.inf], np.nan).fillna(0.0)'
        for spec in specs
    )
    return (
        f"{HELPERS}\n\n"
        f"FACTOR_METADATA = {metadata!r}\n\n"
        f"fields = {fields!r}\n\n\n"
        "def compute_factor(code: str, date: str, df: pd.DataFrame) -> pd.DataFrame:\n"
        "    del code, date\n"
        "    out = {}\n"
        f"{assignments}\n"
        "    return pd.DataFrame(out, index=df.index).reset_index(drop=True)\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate executable proxy tests directly from LLM paper_hf_factors.")
    parser.add_argument("--input", default="data/analysis_archive.jsonl", help="JSONL file containing cumulative LLM paper_hf_factors.")
    parser.add_argument("--output-dir", default="data/paper_hf_factor_tests", help="Output directory for generated factor file.")
    parser.add_argument("--dedup-key", default="paper_hf_direct_proxy_tests", help="Generated factor file stem.")
    parser.add_argument("--limit", type=int, default=6, help="Maximum paper_hf_factors to render; 0 means all renderable.")
    parser.add_argument("--templates", default=str(DEFAULT_TEMPLATE_PATH.relative_to(PROJECT_ROOT)), help="YAML config declaring allowed proxy operators and templates.")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / input_path
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    template_path = Path(args.templates)
    if not template_path.is_absolute():
        template_path = PROJECT_ROOT / template_path

    specs = build_factor_specs(input_path, int(args.limit), template_path)
    if not specs:
        raise RuntimeError(f"no renderable direct/derived paper_hf_factors found in {input_path}")
    factor_path = output_dir / f"{args.dedup_key}.py"
    factor_path.write_text(render_factor_file(specs, template_path), encoding="utf-8")
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"schema_version": 1, "source": str(input_path), "factor_file": str(factor_path), "template_config": str(template_path), "specs": specs}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "count": len(specs), "factor_file": str(factor_path), "manifest": str(manifest_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()