from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from agent_alpha.factors.expression_validator import validate_factor_candidate
from agent_alpha.factors.factor_schema import FactorCandidate
from agent_alpha.factors.prefix_expression import prefix_to_expression


def _python_string(value: str) -> str:
    return repr(str(value))


def _series(field: str) -> str:
    return f"pd.to_numeric(features[{field!r}], errors='coerce')"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _prefix_op_args(node: Any) -> tuple[str, list[Any]]:
    if isinstance(node, list) and node:
        return str(node[0]), list(node[1:])
    if isinstance(node, dict):
        op = str(node.get("op") or "")
        args = node.get("args", [])
        if not isinstance(args, list):
            args = [args]
        return op, list(args)
    raise ValueError(f"invalid prefix node: {node!r}")


def render_prefix_to_python(node: Any) -> str:
    if isinstance(node, str):
        return _series(node)
    if _is_number(node):
        return repr(node)
    op, args = _prefix_op_args(node)
    render = render_prefix_to_python
    if op in {"add", "sub", "mul", "div"}:
        symbol = {"add": "+", "sub": "-", "mul": "*", "div": "/"}[op]
        return f"({render(args[0])} {symbol} {render(args[1])})"
    if op == "neg":
        return f"(-{render(args[0])})"
    if op == "safe_div":
        return f"({render(args[0])} / ({render(args[1])} + eps))"
    if op == "abs":
        return f"({render(args[0])}).abs()"
    if op == "clip":
        return f"({render(args[0])}).clip(lower={render(args[1])}, upper={render(args[2])})"
    if op == "log1p":
        return f"np.log1p({render(args[0])})"
    if op == "log":
        return f"np.log(({render(args[0])}).abs() + eps)"
    if op == "tanh":
        return f"np.tanh({render(args[0])})"
    if op == "sign":
        return f"np.sign({render(args[0])})"
    if op == "rank":
        return f"({render(args[0])}).rank(pct=True)"
    if op == "zscore":
        return f"_zscore({render(args[0])}, {int(args[1]) if len(args) > 1 else 60})"
    rolling_methods = {
        "rolling_mean": "mean", "rolling_std": "std", "rolling_sum": "sum",
        "rolling_min": "min", "rolling_max": "max", "rolling_median": "median",
    }
    if op in rolling_methods:
        return f"({render(args[0])}).rolling({int(args[1])}, min_periods=1).{rolling_methods[op]}()"
    if op == "rolling_rank":
        return f"_rolling_rank({render(args[0])}, {int(args[1])})"
    if op == "rolling_count":
        return f"({render(args[0])}).astype(float).rolling({int(args[1])}, min_periods=1).sum()"
    if op in {"ewm_mean", "ewm_std"}:
        method = "mean" if op == "ewm_mean" else "std"
        return f"({render(args[0])}).ewm(halflife={int(args[1])}, min_periods=1, adjust=True).{method}()"
    if op in {"diff", "shift", "pct_change"}:
        return f"({render(args[0])}).{op}({int(args[1])})"
    if op in {"max", "min"}:
        return f"np.{'maximum' if op == 'max' else 'minimum'}({render(args[0])}, {render(args[1])})"
    comparison = {"gt": ">", "lt": "<", "ge": ">=", "le": "<=", "eq": "==", "neq": "!="}
    if op in comparison:
        return f"({render(args[0])} {comparison[op]} {render(args[1])})"
    if op in {"and", "or"}:
        return f"(({render(args[0])}) {'&' if op == 'and' else '|'} ({render(args[1])}))"
    if op == "where":
        return f"pd.Series(np.where({render(args[0])}, {render(args[1])}, {render(args[2])}), index=df.index)"
    if op in {"rolling_corr", "rolling_cov"}:
        method = "corr" if op == "rolling_corr" else "cov"
        return f"({render(args[0])}).rolling({int(args[2])}, min_periods=2).{method}({render(args[1])})"
    if op == "rolling_beta":
        return f"_rolling_beta({render(args[0])}, {render(args[1])}, {int(args[2])})"
    if op in {"div_mean", "div_std"}:
        method = "mean" if op == "div_mean" else "std"
        return f"({render(args[0])} / ({render(args[1])} + eps)).rolling({int(args[2])}, min_periods=1).{method}()"
    if op == "vol_scale":
        value = render(args[0])
        return f"({value} / (({value}).rolling({int(args[1])}, min_periods=1).std() + eps))"
    raise ValueError(f"unsupported prefix op: {op}")


def _translate_arithmetic(expr: str) -> str:
    tree = ast.parse(expr, mode="eval")

    def visit(node: ast.AST) -> str:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Name):
            return _series(node.id)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return repr(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return f"(-{visit(node.operand)})"
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            op = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}[type(node.op)]
            return f"({visit(node.left)} {op} {visit(node.right)})"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name == "abs" and len(node.args) == 1:
                return f"({visit(node.args[0])}).abs()"
            if name == "log1p" and len(node.args) == 1:
                return f"np.log1p({visit(node.args[0])})"
            if name == "rank" and len(node.args) == 1:
                return f"({visit(node.args[0])}).rank(pct=True)"
            if name == "clip" and len(node.args) == 3:
                return f"({visit(node.args[0])}).clip(lower={visit(node.args[1])}, upper={visit(node.args[2])})"
        raise ValueError(f"unsupported expression node: {ast.dump(node)}")

    return visit(tree)


def _split_args(raw: str) -> list[str]:
    args: list[str] = []
    depth = 0
    start = 0
    for idx, char in enumerate(raw):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            args.append(raw[start:idx].strip())
            start = idx + 1
    args.append(raw[start:].strip())
    return args


def render_expression_to_python(expression: str) -> str:
    expr = expression.strip()
    match = re.fullmatch(r"safe_div\((.*)\)", expr)
    if match:
        args = _split_args(match.group(1))
        if len(args) != 2:
            raise ValueError("safe_div requires exactly two arguments")
        return f"(({_translate_arithmetic(args[0])}) / (({_translate_arithmetic(args[1])}) + eps))"
    match = re.fullmatch(r"rolling_mean\((.*),\s*(\d+)\)", expr)
    if match:
        return f"({_translate_arithmetic(match.group(1))}).rolling({int(match.group(2))}, min_periods=1).mean()"
    match = re.fullmatch(r"rolling_std\((.*),\s*(\d+)\)", expr)
    if match:
        return f"({_translate_arithmetic(match.group(1))}).rolling({int(match.group(2))}, min_periods=1).std()"
    match = re.fullmatch(r"zscore\((.*?)(?:,\s*(\d+))?\)", expr)
    if match:
        window = int(match.group(2) or 60)
        return f"_zscore({_translate_arithmetic(match.group(1))}, {window})"
    return _translate_arithmetic(expr)


def render_fac_eval_factor(candidate: dict, output_dir: str | Path = "data/factors") -> Path:
    factor = candidate if isinstance(candidate, FactorCandidate) else FactorCandidate.from_mapping(candidate)
    validation = validate_factor_candidate(factor)
    if not validation.ok:
        raise ValueError(f"invalid factor candidate: {validation.message}")
    factor_name = factor.name
    rendered = render_prefix_to_python(factor.prefix_expression) if factor.prefix_expression is not None else render_expression_to_python(factor.expression)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{factor_name}.py"
    code = f'''from __future__ import annotations

import numpy as np
import pandas as pd

fields = [{_python_string(factor_name)}]


def _zscore(series: pd.Series, window: int = 60) -> pd.Series:
    mean = series.rolling(window, min_periods=1).mean()
    std = series.rolling(window, min_periods=1).std().replace(0, np.nan)
    return (series - mean) / (std + 1e-12)


def _rolling_rank(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=1).apply(lambda values: pd.Series(values).rank(pct=True).iloc[-1], raw=False)


def _rolling_beta(y: pd.Series, x: pd.Series, window: int) -> pd.Series:
    cov = y.rolling(window, min_periods=2).cov(x)
    var = x.rolling(window, min_periods=2).var()
    return cov / (var + 1e-12)


def compute_factor(code: str, date: str, df: pd.DataFrame) -> pd.DataFrame:
    """Generated baseline HF factor: {factor_name}."""
    eps = 1e-12
    features = _add_basic_hf_features(df.copy())
    out = pd.DataFrame(index=df.index)
    out[{_python_string(factor_name)}] = {rendered}
    return out


def _add_basic_hf_features(features: pd.DataFrame) -> pd.DataFrame:
    """Build stable derived fields used by the controlled DSL renderer."""
    eps = 1e-12
    if "askP1" in features and "bidP1" in features:
        ask_p1 = pd.to_numeric(features["askP1"], errors="coerce")
        bid_p1 = pd.to_numeric(features["bidP1"], errors="coerce")
        features["spread_l1"] = ask_p1 - bid_p1
        features["mid_price_l1"] = (ask_p1 + bid_p1) / 2.0
        features["relative_spread_l1"] = features["spread_l1"] / (features["mid_price_l1"] + eps)
    if "askV1" in features and "bidV1" in features:
        ask_v1 = pd.to_numeric(features["askV1"], errors="coerce")
        bid_v1 = pd.to_numeric(features["bidV1"], errors="coerce")
        features["depth_imbalance_l1"] = (bid_v1 - ask_v1) / (bid_v1 + ask_v1 + eps)
        if "askP1" in features and "bidP1" in features:
            ask_p1 = pd.to_numeric(features["askP1"], errors="coerce")
            bid_p1 = pd.to_numeric(features["bidP1"], errors="coerce")
            features["microprice_l1"] = (ask_p1 * bid_v1 + bid_p1 * ask_v1) / (ask_v1 + bid_v1 + eps)
    if "volume" in features:
        volume = pd.to_numeric(features["volume"], errors="coerce")
        features["log_volume"] = np.log1p(volume.replace(0, np.nan))
        features["volume_shock_20_120"] = volume.rolling(20, min_periods=1).mean() / (volume.rolling(120, min_periods=1).mean() + eps)
        features["activity_surge_20_120"] = volume.abs().rolling(20, min_periods=1).sum() / (volume.abs().rolling(120, min_periods=1).mean() + eps)
    return features
'''
    path.write_text(code, encoding="utf-8")
    return path
