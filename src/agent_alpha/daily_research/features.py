from __future__ import annotations

import numpy as np
import pandas as pd


RETURN_ONLY_OPERATORS = frozenset({
	"momentum_sum",
	"reversal_sum",
	"mean_return",
	"volatility",
	"downside_volatility",
	"skewness",
	"kurtosis",
	"max_return",
	"min_return",
	"autocorrelation_lag1",
	"market_residual_momentum",
})


def compute_return_only_feature(
	returns: pd.DataFrame,
	*,
	operator: str,
	window: int,
	min_periods: int | None = None,
) -> pd.DataFrame:
	"""Compute one causal feature using only returns observed through date t."""

	if operator not in RETURN_ONLY_OPERATORS:
		raise ValueError(f"operator is not approved for return-only research: {operator}")
	if not isinstance(window, int) or isinstance(window, bool) or window < 2:
		raise ValueError("window must be an integer >= 2")
	minimum = int(min_periods if min_periods is not None else window)
	if minimum < 2 or minimum > window:
		raise ValueError("min_periods must be between 2 and window")
	values = returns.astype(float)
	rolling = values.rolling(window=window, min_periods=minimum)
	if operator == "momentum_sum":
		result = rolling.sum()
	elif operator == "reversal_sum":
		result = -rolling.sum()
	elif operator == "mean_return":
		result = rolling.mean()
	elif operator == "volatility":
		result = rolling.std(ddof=1)
	elif operator == "downside_volatility":
		downside_square = values.where(values < 0.0, 0.0).pow(2)
		result = np.sqrt(downside_square.rolling(window, min_periods=minimum).mean())
	elif operator == "skewness":
		result = rolling.skew()
	elif operator == "kurtosis":
		result = rolling.kurt()
	elif operator == "max_return":
		result = rolling.max()
	elif operator == "min_return":
		result = rolling.min()
	elif operator == "autocorrelation_lag1":
		result = values.rolling(window, min_periods=minimum).corr(values.shift(1))
	else:
		market_return = values.mean(axis=1, skipna=True)
		residual = values.sub(market_return, axis=0)
		result = residual.rolling(window, min_periods=minimum).sum()
	result.attrs.update({
		"causal_availability": "after_close_t",
		"input_observables": ["RETURN_HISTORY"],
		"operator": operator,
		"window": window,
		"min_periods": minimum,
	})
	return result


__all__ = ["RETURN_ONLY_OPERATORS", "compute_return_only_feature"]
