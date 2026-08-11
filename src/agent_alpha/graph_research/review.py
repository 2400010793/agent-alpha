from __future__ import annotations

import operator
import re
from collections.abc import Sequence
from typing import Callable

from .ids import sha256_content_hash
from .models import ExperimentNodeV1, ExperimentReviewV1, RunAttemptV1
from .ports import ExperimentReviewResult, MetricRecord
from .states import RunAttemptStatus, ScientificVerdict


class AcceptanceRuleError(ValueError):
	pass


_RULE = re.compile(
	r"\s*(?P<metric>[A-Za-z_][A-Za-z0-9_.:/-]*)\s*"
	r"(?P<operator>>=|<=|==|>|<)\s*"
	r"(?P<threshold>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*"
)
_OPERATORS: dict[str, Callable[[float, float], bool]] = {
	">": operator.gt, ">=": operator.ge, "<": operator.lt,
	"<=": operator.le, "==": operator.eq,
}


def evaluate_acceptance_rule(
	acceptance_rule: str, metrics: Sequence[MetricRecord],
) -> tuple[ScientificVerdict, str, float | None, str]:
	"""Evaluate one exact preregistered comparison without natural-language guessing."""
	if not isinstance(acceptance_rule, str) or not acceptance_rule.strip():
		raise AcceptanceRuleError("acceptance_rule must be non-empty")
	match = _RULE.fullmatch(acceptance_rule)
	if match is None:
		raise AcceptanceRuleError(
			"acceptance_rule must use '<metric> <operator> <number>'"
		)
	metric_name = match.group("metric")
	values = [metric.value for metric in metrics if metric.metric_name == metric_name]
	if len(values) > 1:
		raise AcceptanceRuleError(f"duplicate primary metric: {metric_name}")
	if not values:
		return ScientificVerdict.INCONCLUSIVE, metric_name, None, "primary_metric_missing"
	value = values[0]
	threshold = float(match.group("threshold"))
	passed = _OPERATORS[match.group("operator")](value, threshold)
	return (
		ScientificVerdict.SUPPORTED if passed else ScientificVerdict.REFUTED,
		metric_name,
		value,
		"acceptance_rule_passed" if passed else "acceptance_rule_failed",
	)


def build_rule_based_review(
	*, experiment: ExperimentNodeV1, attempt: RunAttemptV1,
	metrics: tuple[MetricRecord, ...], reviewer_revision: str, reviewed_at: str,
) -> ExperimentReviewResult:
	if attempt.experiment_id != experiment.experiment_id:
		raise ValueError("attempt does not belong to experiment")
	if attempt.status != RunAttemptStatus.SUCCEEDED:
		raise ValueError("scientific review requires a successful run attempt")
	if not isinstance(metrics, tuple):
		raise TypeError("metrics must be tuple[MetricRecord, ...]")
	for metric in metrics:
		if not isinstance(metric, MetricRecord):
			raise TypeError("metrics must contain only MetricRecord values")
		if metric.experiment_id != experiment.experiment_id:
			raise ValueError("metric belongs to a different experiment")
		if metric.source_artifact_id not in attempt.result_artifacts:
			raise ValueError("metric source is not a result artifact from the successful attempt")
	verdict, metric_name, metric_value, reason_code = evaluate_acceptance_rule(
		experiment.acceptance_rule, metrics,
	)
	if metric_name != experiment.pre_registered_primary_metric:
		raise AcceptanceRuleError("acceptance rule metric differs from preregistered primary metric")
	metric_payload = [metric.to_dict() for metric in sorted(metrics, key=lambda item: item.registry_key)]
	review = ExperimentReviewV1.create(
		experiment_id=experiment.experiment_id, run_attempt_id=attempt.run_attempt_id,
		primary_metric_name=metric_name, primary_metric_value=metric_value,
		acceptance_rule=experiment.acceptance_rule, verdict=verdict,
		reason_codes=(reason_code,), metrics_content_hash=sha256_content_hash(metric_payload),
		reviewer_revision=reviewer_revision, reviewed_at=reviewed_at,
	)
	return ExperimentReviewResult(review=review, metrics=metrics)


__all__ = ["AcceptanceRuleError", "build_rule_based_review", "evaluate_acceptance_rule"]
