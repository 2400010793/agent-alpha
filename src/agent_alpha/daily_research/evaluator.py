from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

from agent_alpha.graph_research.ids import deterministic_id


STAGES = frozenset({"exploration", "validation", "locked_test"})


@dataclass(frozen=True)
class DailyEvaluationResultV1:
	evaluation_id: str
	factor_id: str
	stage: str
	horizon: int
	direction: str
	date_start: str
	date_end: str
	daily_rankic_mean: float
	daily_rankic_std: float
	rankicir: float
	positive_rankic_ratio: float
	qspread_mean: float
	finite_ratio: float
	n_dates: int
	n_observations: int
	min_cross_sectional_obs: int
	anomaly_policy: Mapping[str, Any]
	schema_version: str = "daily_evaluation_result_v1"

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)


def sanitize_daily_returns(
	returns: pd.DataFrame, *, max_abs_return: float = 1.0
) -> pd.DataFrame:
	if not 0 < max_abs_return <= 10:
		raise ValueError("max_abs_return must be in (0, 10]")
	values = returns.astype(float).replace([np.inf, -np.inf], np.nan)
	return values.mask(values.abs() > max_abs_return)


def forward_compound_return(returns: pd.DataFrame, horizon: int) -> pd.DataFrame:
	"""Label date t with the compounded returns from t+1 through t+h."""

	if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1:
		raise ValueError("horizon must be a positive integer")
	pieces = [1.0 + returns.shift(-offset) for offset in range(1, horizon + 1)]
	result = pieces[0]
	valid = pieces[0].notna()
	for piece in pieces[1:]:
		result = result * piece
		valid &= piece.notna()
	return (result - 1.0).where(valid)


def _date_slice(frame: pd.DataFrame, date_start: str, date_end: str) -> pd.DataFrame:
	start = pd.Timestamp(date_start)
	end = pd.Timestamp(date_end)
	if end < start:
		raise ValueError("date_end cannot precede date_start")
	return frame.loc[(frame.index >= start) & (frame.index <= end)]


def _daily_rankic(feature: pd.DataFrame, label: pd.DataFrame, minimum: int) -> pd.Series:
	values: dict[pd.Timestamp, float] = {}
	for date in feature.index:
		valid = feature.loc[date].notna() & label.loc[date].notna()
		if int(valid.sum()) < minimum:
			continue
		left = feature.loc[date, valid].rank(method="average")
		right = label.loc[date, valid].rank(method="average")
		value = left.corr(right)
		if value is not None and math.isfinite(float(value)):
			values[date] = float(value)
	return pd.Series(values, dtype=float)


def _daily_qspread(feature: pd.DataFrame, label: pd.DataFrame, minimum: int) -> pd.Series:
	values: dict[pd.Timestamp, float] = {}
	for date in feature.index:
		valid = feature.loc[date].notna() & label.loc[date].notna()
		count = int(valid.sum())
		if count < minimum:
			continue
		ranks = feature.loc[date, valid].rank(method="first", pct=True)
		future = label.loc[date, valid]
		top = future[ranks > 0.8]
		bottom = future[ranks <= 0.2]
		if not top.empty and not bottom.empty:
			values[date] = float(top.mean() - bottom.mean())
	return pd.Series(values, dtype=float)


def evaluate_daily_factor_detailed(
	feature: pd.DataFrame,
	returns: pd.DataFrame,
	*,
	factor_id: str,
	stage: str,
	date_start: str,
	date_end: str,
	horizon: int,
	direction: str,
	min_cross_sectional_obs: int = 100,
	max_abs_return: float = 1.0,
) -> tuple[DailyEvaluationResultV1, pd.DataFrame]:
	if stage not in STAGES:
		raise ValueError(f"unsupported daily evaluation stage: {stage}")
	if direction not in {"positive", "negative"}:
		raise ValueError("direction must be positive or negative")
	if min_cross_sectional_obs < 5:
		raise ValueError("min_cross_sectional_obs must be at least 5")
	if not feature.index.equals(returns.index) or not feature.columns.equals(returns.columns):
		raise ValueError("feature and returns must have exactly aligned axes")
	clean = sanitize_daily_returns(returns, max_abs_return=max_abs_return)
	label = forward_compound_return(clean, horizon)
	feature_stage = _date_slice(feature.replace([np.inf, -np.inf], np.nan), date_start, date_end)
	label_stage = label.reindex(index=feature_stage.index, columns=feature_stage.columns)
	rankic = _daily_rankic(feature_stage, label_stage, min_cross_sectional_obs)
	qspread = _daily_qspread(feature_stage, label_stage, min_cross_sectional_obs)
	valid = feature_stage.notna() & label_stage.notna()
	n_observations = int(valid.to_numpy().sum())
	finite_ratio = n_observations / max(1, int(label_stage.notna().to_numpy().sum()))
	mean = float(rankic.mean()) if not rankic.empty else float("nan")
	std = float(rankic.std(ddof=1)) if len(rankic) > 1 else float("nan")
	rankicir = mean / std if math.isfinite(std) and std > 0 else float("nan")
	positive_ratio = float((rankic > 0).mean()) if not rankic.empty else float("nan")
	qspread_mean = float(qspread.mean()) if not qspread.empty else float("nan")
	identity = {
		"factor_id": factor_id,
		"stage": stage,
		"date_start": date_start,
		"date_end": date_end,
		"horizon": horizon,
		"direction": direction,
		"min_cross_sectional_obs": min_cross_sectional_obs,
		"max_abs_return": max_abs_return,
	}
	result = DailyEvaluationResultV1(
		evaluation_id=deterministic_id("dailyeval", identity),
		factor_id=factor_id,
		stage=stage,
		horizon=horizon,
		direction=direction,
		date_start=date_start,
		date_end=date_end,
		daily_rankic_mean=mean,
		daily_rankic_std=std,
		rankicir=rankicir,
		positive_rankic_ratio=positive_ratio,
		qspread_mean=qspread_mean,
		finite_ratio=float(finite_ratio),
		n_dates=len(rankic),
		n_observations=n_observations,
		min_cross_sectional_obs=min_cross_sectional_obs,
		anomaly_policy={"mask_abs_return_gt": max_abs_return, "zero_return_policy": "preserve"},
	)
	daily = pd.DataFrame({
		"daily_rankic": rankic,
		"qspread": qspread,
	}).sort_index()
	daily["n_obs"] = valid.sum(axis=1).reindex(daily.index).astype(int)
	daily.index.name = "date"
	return result, daily


def evaluate_daily_factor(
	feature: pd.DataFrame,
	returns: pd.DataFrame,
	*,
	factor_id: str,
	stage: str,
	date_start: str,
	date_end: str,
	horizon: int,
	direction: str,
	min_cross_sectional_obs: int = 100,
	max_abs_return: float = 1.0,
) -> DailyEvaluationResultV1:
	return evaluate_daily_factor_detailed(
		feature,
		returns,
		factor_id=factor_id,
		stage=stage,
		date_start=date_start,
		date_end=date_end,
		horizon=horizon,
		direction=direction,
		min_cross_sectional_obs=min_cross_sectional_obs,
		max_abs_return=max_abs_return,
	)[0]


__all__ = [
	"DailyEvaluationResultV1",
	"STAGES",
	"evaluate_daily_factor",
	"evaluate_daily_factor_detailed",
	"forward_compound_return",
	"sanitize_daily_returns",
]
