import pytest

from agent_alpha.daily_research.experiment import DailyExperimentSpecV1


def _spec(**overrides):
	values = {
		"package_id": "researchpkg:one",
		"hypothesis_id": "hypothesis:one",
		"factor_id": "daily_momentum_20",
		"operator": "momentum_sum",
		"window": 20,
		"min_periods": 20,
		"horizon": 5,
		"direction": "positive",
		"stage": "validation",
		"date_start": "2020-01-01",
		"date_end": "2021-12-31",
		"min_cross_sectional_obs": 100,
		"max_abs_return": 1.0,
		"data_contract_id": "daily_ret_wide_v1",
		"data_contract_hash": "contracthash",
		"operator_registry_version": "daily_return_operator_registry_v1",
	}
	values.update(overrides)
	return DailyExperimentSpecV1.create(**values)


def test_daily_experiment_identity_covers_stage_and_split() -> None:
	validation = _spec()
	locked = _spec(stage="locked_test")
	other_dates = _spec(date_end="2022-12-31")
	assert validation.daily_experiment_id != locked.daily_experiment_id
	assert validation.daily_experiment_id != other_dates.daily_experiment_id
	assert DailyExperimentSpecV1.from_mapping(validation.to_dict()) == validation


def test_daily_experiment_rejects_unapproved_operator() -> None:
	with pytest.raises(ValueError, match="unapproved"):
		_spec(operator="volume_momentum")
