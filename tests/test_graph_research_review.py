from __future__ import annotations

import pytest

from agent_alpha.graph_research.models import ExperimentNodeV1, RunAttemptV1
from agent_alpha.graph_research.ports import MetricRecord
from agent_alpha.graph_research.review import AcceptanceRuleError, build_rule_based_review, evaluate_acceptance_rule
from agent_alpha.graph_research.states import OperationType, RunAttemptStatus, ScientificVerdict


def _experiment(**overrides: object) -> ExperimentNodeV1:
	values: dict[str, object] = {
		"hypothesis_id": "hyp_1", "operation_type": OperationType.PRIMARY_TEST,
		"factor_instance_ids": ["factor_1"],
		"pre_registered_primary_metric": "rank_ic",
		"acceptance_rule": "rank_ic >= 0.02", "universe": "csi500",
		"market_data_version": "snapshot_1", "train_window": "2020",
		"validation_window": "2021", "test_window": "2022", "embargo": 5,
		"purge": 5, "cost_assumptions": {}, "robustness_dimensions": [],
		"budget_id": "budget_1",
	}
	values.update(overrides)
	return ExperimentNodeV1.create(**values)


def _attempt(experiment_id: str) -> RunAttemptV1:
	return RunAttemptV1.create(
		experiment_id=experiment_id, attempt_number=1, code_hash="code",
		environment_hash="env", scheduler="fake", resources={}, timeout_seconds=60,
		result_artifacts=("artifact_1",), exit_code=0,
		started_at="2026-08-10T10:00:00+00:00",
		completed_at="2026-08-10T10:01:00+00:00",
		status=RunAttemptStatus.SUCCEEDED,
	)


def _metric(experiment_id: str, value: float = 0.03) -> MetricRecord:
	return MetricRecord(
		metric_name="rank_ic", experiment_id=experiment_id, value=value,
		source_artifact_id="artifact_1", content_hash="metric_hash_1",
	)


@pytest.mark.parametrize(
	("rule", "value", "verdict"),
	[
		("rank_ic > 0.02", 0.03, ScientificVerdict.SUPPORTED),
		("rank_ic >= 0.02", 0.02, ScientificVerdict.SUPPORTED),
		("rank_ic < -1e-2", -0.02, ScientificVerdict.SUPPORTED),
		("rank_ic <= 0.02", 0.03, ScientificVerdict.REFUTED),
		("rank_ic == 0.02", 0.01, ScientificVerdict.REFUTED),
	],
)
def test_exact_acceptance_rule_operators(rule: str, value: float, verdict: ScientificVerdict) -> None:
	result, metric_name, metric_value, _ = evaluate_acceptance_rule(rule, (_metric("exp_1", value),))
	assert result == verdict
	assert metric_name == "rank_ic"
	assert metric_value == value


def test_acceptance_rule_missing_metric_is_inconclusive() -> None:
	verdict, metric_name, value, reason = evaluate_acceptance_rule("rank_ic > 0.02", ())
	assert (verdict, metric_name, value, reason) == (
		ScientificVerdict.INCONCLUSIVE, "rank_ic", None, "primary_metric_missing",
	)


@pytest.mark.parametrize(
	"rule",
	[
		"rank_ic > 0.02 on the test window",
		"rank_ic is positive",
		"rank_ic > other_metric",
		"rank_ic > 0.02 and turnover < 0.5",
	],
)
def test_acceptance_rule_rejects_natural_language_and_compound_guessing(rule: str) -> None:
	with pytest.raises(AcceptanceRuleError):
		evaluate_acceptance_rule(rule, (_metric("exp_1"),))


def test_rule_based_review_binds_metric_to_successful_attempt_artifact() -> None:
	experiment = _experiment()
	attempt = _attempt(experiment.experiment_id)
	result = build_rule_based_review(
		experiment=experiment, attempt=attempt, metrics=(_metric(experiment.experiment_id),),
		reviewer_revision="rule_reviewer_v1", reviewed_at="2026-08-10T10:02:00+00:00",
	)
	assert result.review.verdict == ScientificVerdict.SUPPORTED
	assert result.review.run_attempt_id == attempt.run_attempt_id
	assert result.review.primary_metric_value == 0.03

	wrong_artifact = MetricRecord(
		metric_name="rank_ic", experiment_id=experiment.experiment_id, value=0.03,
		source_artifact_id="artifact_other", content_hash="metric_hash_2",
	)
	with pytest.raises(ValueError, match="not a result artifact"):
		build_rule_based_review(
			experiment=experiment, attempt=attempt, metrics=(wrong_artifact,),
			reviewer_revision="rule_reviewer_v1", reviewed_at="2026-08-10T10:02:00+00:00",
		)


def test_rule_based_review_rejects_metric_name_drift_from_preregistration() -> None:
	experiment = _experiment(
		pre_registered_primary_metric="direction_adjusted_rank_ic",
		acceptance_rule="rank_ic > 0.02",
	)
	with pytest.raises(AcceptanceRuleError, match="differs"):
		build_rule_based_review(
			experiment=experiment, attempt=_attempt(experiment.experiment_id),
			metrics=(_metric(experiment.experiment_id),), reviewer_revision="rule_reviewer_v1",
			reviewed_at="2026-08-10T10:02:00+00:00",
		)
