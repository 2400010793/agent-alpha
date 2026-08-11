import numpy as np
import pandas as pd
import pytest

from agent_alpha.daily_research.evaluator import (
	evaluate_daily_factor,
	forward_compound_return,
	sanitize_daily_returns,
)
from agent_alpha.daily_research.features import compute_return_only_feature


def _returns(rows=20, columns=120):
	index = pd.date_range("2020-01-01", periods=rows, freq="D")
	values = np.arange(rows * columns, dtype=float).reshape(rows, columns)
	values = ((values % 17) - 8) / 1000.0
	return pd.DataFrame(values, index=index, columns=[f"S{i:03d}" for i in range(columns)])


def test_forward_label_starts_at_next_date_and_compounds() -> None:
	returns = pd.DataFrame({"A": [0.1, 0.2, -0.1, 0.3]}, index=pd.date_range("2020-01-01", periods=4))
	label = forward_compound_return(returns, 2)
	assert label.iloc[0, 0] == pytest.approx((1.2 * 0.9) - 1.0)
	assert pd.isna(label.iloc[-2, 0])


def test_return_only_feature_is_causal() -> None:
	returns = _returns(rows=10, columns=5)
	before = compute_return_only_feature(returns, operator="momentum_sum", window=3)
	mutated = returns.copy()
	mutated.iloc[-1] = 99.0
	after = compute_return_only_feature(mutated, operator="momentum_sum", window=3)
	pd.testing.assert_frame_equal(before.iloc[:-1], after.iloc[:-1])


def test_daily_evaluator_reports_cross_sectional_rankic_without_future_leakage() -> None:
	returns = _returns()
	feature = compute_return_only_feature(returns, operator="reversal_sum", window=3)
	result = evaluate_daily_factor(
		feature,
		returns,
		factor_id="daily_reversal_3",
		stage="validation",
		date_start="2020-01-04",
		date_end="2020-01-17",
		horizon=1,
		direction="positive",
		min_cross_sectional_obs=100,
	)
	assert result.stage == "validation"
	assert result.n_dates > 0
	assert result.n_observations >= result.n_dates * 100
	assert result.anomaly_policy["zero_return_policy"] == "preserve"


def test_daily_evaluator_masks_extreme_returns_and_rejects_axis_drift() -> None:
	returns = _returns()
	returns.iloc[5, 0] = 19.0
	feature = compute_return_only_feature(returns, operator="volatility", window=3)
	result = evaluate_daily_factor(
		feature,
		returns,
		factor_id="daily_vol_3",
		stage="exploration",
		date_start="2020-01-04",
		date_end="2020-01-15",
		horizon=1,
		direction="negative",
		min_cross_sectional_obs=100,
	)
	assert pd.isna(sanitize_daily_returns(returns).iloc[5, 0])
	assert result.anomaly_policy["mask_abs_return_gt"] == 1.0
	with pytest.raises(ValueError, match="aligned axes"):
		evaluate_daily_factor(
			feature.iloc[:, :-1], returns, factor_id="bad", stage="exploration",
			date_start="2020-01-04", date_end="2020-01-15", horizon=1,
			direction="positive", min_cross_sectional_obs=100,
		)


def test_unapproved_daily_operator_is_rejected() -> None:
	with pytest.raises(ValueError, match="not approved"):
		compute_return_only_feature(_returns(), operator="volume_momentum", window=5)
