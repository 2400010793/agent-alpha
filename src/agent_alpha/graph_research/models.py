from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from types import MappingProxyType
from typing import Any, Iterable, Optional, Type, TypeVar

from .ids import (
	NO_EVIDENCE,
	experiment_review_id as make_experiment_review_id,
	experiment_id as make_experiment_id,
	hypothesis_id as make_hypothesis_id,
	normalize_identity_ids,
	research_run_id as make_research_run_id,
	run_attempt_id as make_run_attempt_id,
)
from .states import (
	ExperimentStatus,
	GateStatus,
	HypothesisStatus,
	OperationType,
	RunAttemptStatus,
	ScientificVerdict,
	StructuredDecision,
)


EnumT = TypeVar("EnumT")


def _required(value: Any, field_name: str) -> str:
	if not isinstance(value, str) or not value.strip():
		raise ValueError("%s must be a non-empty string" % field_name)
	return value.strip()


def _optional_string(value: Any, field_name: str) -> Optional[str]:
	if value is None:
		return None
	return _required(value, field_name)


def _enum(value: Any, enum_type: Type[EnumT], field_name: str) -> EnumT:
	if isinstance(value, enum_type):
		return value
	try:
		return enum_type(value)
	except (TypeError, ValueError):
		raise ValueError("unknown %s: %r" % (field_name, value)) from None


def _utc_iso(value: Any, field_name: str, *, optional: bool = False) -> Optional[str]:
	if value is None and optional:
		return None
	text = _required(value, field_name)
	try:
		parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
	except ValueError:
		raise ValueError("%s must be a valid ISO 8601 timestamp" % field_name) from None
	if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
		raise ValueError("%s must include the UTC timezone" % field_name)
	return text


def _freeze(value: Any) -> Any:
	if isinstance(value, Mapping):
		return MappingProxyType({str(key): _freeze(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))})
	if isinstance(value, (list, tuple)):
		return tuple(_freeze(item) for item in value)
	if isinstance(value, set):
		return tuple(sorted((_freeze(item) for item in value), key=repr))
	return value


def _thaw(value: Any) -> Any:
	if isinstance(value, Mapping):
		return {str(key): _thaw(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
	if isinstance(value, tuple):
		return [_thaw(item) for item in value]
	if hasattr(value, "value"):
		return value.value
	return value


def _ordered_strings(values: Iterable[str], field_name: str) -> tuple[str, ...]:
	if isinstance(values, (str, bytes)):
		raise ValueError("%s must be a collection" % field_name)
	result = []
	for value in values:
		result.append(_required(value, field_name))
	return tuple(result)


@dataclass(frozen=True)
class GraphResearchContext:
	schema_version: str
	research_run_id: str
	graph_id: str
	graph_version: str
	graph_artifact_id: str
	graph_content_hash: str
	evidence_bundle_id: str
	evidence_content_hash: str
	research_config_hash: str
	snapshot_id: str
	producer_revision: str
	created_at: str

	def __post_init__(self) -> None:
		for field_name in (
			"schema_version",
			"research_run_id",
			"graph_id",
			"graph_version",
			"graph_artifact_id",
			"graph_content_hash",
			"evidence_bundle_id",
			"evidence_content_hash",
			"research_config_hash",
			"snapshot_id",
			"producer_revision",
		):
			object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
		object.__setattr__(self, "created_at", _utc_iso(self.created_at, "created_at"))
		expected = make_research_run_id(
			graph_id=self.graph_id,
			graph_version=self.graph_version,
			graph_artifact_id=self.graph_artifact_id,
			graph_content_hash=self.graph_content_hash,
			evidence_content_hash=self.evidence_content_hash,
			research_config_hash=self.research_config_hash,
			snapshot_id=self.snapshot_id,
		)
		if self.research_run_id != expected:
			raise ValueError("research_run_id does not match immutable context inputs")

	@classmethod
	def create(
		cls,
		*,
		graph_id: str,
		graph_version: str,
		graph_artifact_id: str,
		graph_content_hash: str,
		research_config_hash: str,
		snapshot_id: str,
		producer_revision: str,
		created_at: str,
		evidence_bundle_id: str = NO_EVIDENCE,
		evidence_content_hash: str = NO_EVIDENCE,
		schema_version: str = "graph_research_context_v1",
	) -> "GraphResearchContext":
		run_id = make_research_run_id(
			graph_id=graph_id,
			graph_version=graph_version,
			graph_artifact_id=graph_artifact_id,
			graph_content_hash=graph_content_hash,
			evidence_content_hash=evidence_content_hash,
			research_config_hash=research_config_hash,
			snapshot_id=snapshot_id,
		)
		return cls(
			schema_version=schema_version,
			research_run_id=run_id,
			graph_id=graph_id,
			graph_version=graph_version,
			graph_artifact_id=graph_artifact_id,
			graph_content_hash=graph_content_hash,
			evidence_bundle_id=evidence_bundle_id,
			evidence_content_hash=evidence_content_hash,
			research_config_hash=research_config_hash,
			snapshot_id=snapshot_id,
			producer_revision=producer_revision,
			created_at=created_at,
		)

	def to_dict(self) -> dict[str, Any]:
		return {
			"schema_version": self.schema_version,
			"research_run_id": self.research_run_id,
			"graph_id": self.graph_id,
			"graph_version": self.graph_version,
			"graph_artifact_id": self.graph_artifact_id,
			"graph_content_hash": self.graph_content_hash,
			"evidence_bundle_id": self.evidence_bundle_id,
			"evidence_content_hash": self.evidence_content_hash,
			"research_config_hash": self.research_config_hash,
			"snapshot_id": self.snapshot_id,
			"producer_revision": self.producer_revision,
			"created_at": self.created_at,
		}


@dataclass(frozen=True)
class HypothesisNodeV1:
	schema_version: str
	hypothesis_id: str
	research_run_id: str
	graph_id: str
	statement: str
	mechanism: str
	prediction: str
	market: str
	asset: str
	frequency: str
	horizon: str
	source_paper_ids: tuple[str, ...]
	source_claim_ids: tuple[str, ...]
	evidence_ids: tuple[str, ...]
	relation_evidence_ids: tuple[str, ...]
	novelty_rationale: str
	falsification_criteria: str
	expected_failure_modes: tuple[str, ...]
	status: HypothesisStatus = HypothesisStatus.PROPOSED
	structural_only: bool = False

	def __post_init__(self) -> None:
		for field_name in (
			"schema_version", "hypothesis_id", "research_run_id", "graph_id", "statement",
			"mechanism", "prediction", "market", "asset", "frequency", "horizon",
			"novelty_rationale", "falsification_criteria",
		):
			object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
		for field_name in ("source_paper_ids", "source_claim_ids", "evidence_ids", "relation_evidence_ids"):
			object.__setattr__(self, field_name, normalize_identity_ids(getattr(self, field_name), field_name))
		object.__setattr__(self, "expected_failure_modes", _ordered_strings(self.expected_failure_modes, "expected_failure_modes"))
		object.__setattr__(self, "status", _enum(self.status, HypothesisStatus, "hypothesis status"))
		if not isinstance(self.structural_only, bool):
			raise ValueError("structural_only must be boolean")
		if not self.source_paper_ids:
			raise ValueError("source_paper_ids must be non-empty")
		if not self.structural_only and not self.evidence_ids:
			raise ValueError("factual hypotheses require at least one evidence ID")
		expected = make_hypothesis_id(
			research_run_id=self.research_run_id,
			graph_id=self.graph_id,
			statement=self.statement,
			mechanism=self.mechanism,
			prediction=self.prediction,
			source_paper_ids=self.source_paper_ids,
			source_claim_ids=self.source_claim_ids,
			evidence_ids=self.evidence_ids,
			relation_evidence_ids=self.relation_evidence_ids,
			structural_only=self.structural_only,
		)
		if self.hypothesis_id != expected:
			raise ValueError("hypothesis_id does not match immutable hypothesis inputs")

	@classmethod
	def create(cls, **values: Any) -> "HypothesisNodeV1":
		values = dict(values)
		values.setdefault("schema_version", "hypothesis_node_v1")
		values.setdefault("status", HypothesisStatus.PROPOSED)
		values.setdefault("structural_only", False)
		for name in ("source_claim_ids", "evidence_ids", "relation_evidence_ids", "expected_failure_modes"):
			values.setdefault(name, ())
		values["hypothesis_id"] = make_hypothesis_id(
			research_run_id=values["research_run_id"], graph_id=values["graph_id"],
			statement=values["statement"], mechanism=values["mechanism"], prediction=values["prediction"],
			source_paper_ids=values["source_paper_ids"], source_claim_ids=values["source_claim_ids"],
			evidence_ids=values["evidence_ids"], relation_evidence_ids=values["relation_evidence_ids"],
			structural_only=values["structural_only"],
		)
		return cls(**values)

	def to_dict(self) -> dict[str, Any]:
		return {
			"schema_version": self.schema_version, "hypothesis_id": self.hypothesis_id,
			"research_run_id": self.research_run_id, "graph_id": self.graph_id,
			"statement": self.statement, "mechanism": self.mechanism, "prediction": self.prediction,
			"market": self.market, "asset": self.asset, "frequency": self.frequency, "horizon": self.horizon,
			"source_paper_ids": list(self.source_paper_ids), "source_claim_ids": list(self.source_claim_ids),
			"evidence_ids": list(self.evidence_ids), "relation_evidence_ids": list(self.relation_evidence_ids),
			"novelty_rationale": self.novelty_rationale,
			"falsification_criteria": self.falsification_criteria,
			"expected_failure_modes": list(self.expected_failure_modes),
			"status": self.status.value, "structural_only": self.structural_only,
		}


@dataclass(frozen=True)
class ExperimentNodeV1:
	schema_version: str
	experiment_id: str
	hypothesis_id: str
	parent_experiment_ids: tuple[str, ...]
	operation_type: OperationType
	factor_instance_ids: tuple[str, ...]
	pre_registered_primary_metric: str
	acceptance_rule: str
	universe: str
	market_data_version: str
	train_window: str
	validation_window: str
	test_window: str
	embargo: int
	purge: int
	cost_assumptions: Mapping[str, Any]
	robustness_dimensions: tuple[str, ...]
	budget_id: str
	status: ExperimentStatus
	experiment_version: int

	def __post_init__(self) -> None:
		for name in (
			"schema_version", "experiment_id", "hypothesis_id", "pre_registered_primary_metric",
			"acceptance_rule", "universe", "market_data_version", "train_window",
			"validation_window", "test_window", "budget_id",
		):
			object.__setattr__(self, name, _required(getattr(self, name), name))
		object.__setattr__(self, "parent_experiment_ids", normalize_identity_ids(self.parent_experiment_ids, "parent_experiment_ids"))
		object.__setattr__(self, "factor_instance_ids", normalize_identity_ids(self.factor_instance_ids, "factor_instance_ids"))
		object.__setattr__(self, "robustness_dimensions", normalize_identity_ids(self.robustness_dimensions, "robustness_dimensions"))
		object.__setattr__(self, "operation_type", _enum(self.operation_type, OperationType, "operation_type"))
		object.__setattr__(self, "status", _enum(self.status, ExperimentStatus, "experiment status"))
		if not isinstance(self.experiment_version, int) or isinstance(self.experiment_version, bool) or self.experiment_version < 1:
			raise ValueError("experiment_version must be a positive integer")
		for name in ("embargo", "purge"):
			value = getattr(self, name)
			if not isinstance(value, int) or isinstance(value, bool) or value < 0:
				raise ValueError("%s must be a non-negative integer" % name)
		if not isinstance(self.cost_assumptions, Mapping):
			raise ValueError("cost_assumptions must be a mapping")
		object.__setattr__(self, "cost_assumptions", _freeze(self.cost_assumptions))
		expected = make_experiment_id(
			hypothesis_id=self.hypothesis_id,
			experiment_version=self.experiment_version,
			preregistration=self.preregistration_payload(),
		)
		if self.experiment_id != expected:
			raise ValueError("experiment_id does not match immutable preregistration")

	def preregistration_payload(self) -> dict[str, Any]:
		return {
			"parent_experiment_ids": list(self.parent_experiment_ids),
			"operation_type": self.operation_type.value,
			"factor_instance_ids": list(self.factor_instance_ids),
			"pre_registered_primary_metric": self.pre_registered_primary_metric,
			"acceptance_rule": self.acceptance_rule, "universe": self.universe,
			"market_data_version": self.market_data_version, "train_window": self.train_window,
			"validation_window": self.validation_window, "test_window": self.test_window,
			"embargo": self.embargo, "purge": self.purge,
			"cost_assumptions": _thaw(self.cost_assumptions),
			"robustness_dimensions": list(self.robustness_dimensions), "budget_id": self.budget_id,
		}

	@classmethod
	def create(cls, **values: Any) -> "ExperimentNodeV1":
		values = dict(values)
		values.setdefault("schema_version", "experiment_node_v1")
		values.setdefault("parent_experiment_ids", ())
		values.setdefault("factor_instance_ids", ())
		values.setdefault("robustness_dimensions", ())
		values.setdefault("cost_assumptions", {})
		values.setdefault("status", ExperimentStatus.CREATED)
		values.setdefault("experiment_version", 1)
		operation = _enum(values["operation_type"], OperationType, "operation_type")
		if not isinstance(values["experiment_version"], int) or isinstance(values["experiment_version"], bool) or values["experiment_version"] < 1:
			raise ValueError("experiment_version must be a positive integer")
		for name in ("embargo", "purge"):
			if not isinstance(values[name], int) or isinstance(values[name], bool) or values[name] < 0:
				raise ValueError("%s must be a non-negative integer" % name)
		if not isinstance(values["cost_assumptions"], Mapping):
			raise ValueError("cost_assumptions must be a mapping")
		preregistration = {
			"parent_experiment_ids": list(normalize_identity_ids(values["parent_experiment_ids"], "parent_experiment_ids")),
			"operation_type": operation.value,
			"factor_instance_ids": list(normalize_identity_ids(values["factor_instance_ids"], "factor_instance_ids")),
			"pre_registered_primary_metric": _required(values["pre_registered_primary_metric"], "pre_registered_primary_metric"),
			"acceptance_rule": _required(values["acceptance_rule"], "acceptance_rule"),
			"universe": _required(values["universe"], "universe"),
			"market_data_version": _required(values["market_data_version"], "market_data_version"),
			"train_window": _required(values["train_window"], "train_window"),
			"validation_window": _required(values["validation_window"], "validation_window"),
			"test_window": _required(values["test_window"], "test_window"),
			"embargo": values["embargo"], "purge": values["purge"],
			"cost_assumptions": _thaw(_freeze(values["cost_assumptions"])),
			"robustness_dimensions": list(normalize_identity_ids(values["robustness_dimensions"], "robustness_dimensions")),
			"budget_id": _required(values["budget_id"], "budget_id"),
		}
		values["experiment_id"] = make_experiment_id(
			hypothesis_id=_required(values["hypothesis_id"], "hypothesis_id"),
			experiment_version=values["experiment_version"],
			preregistration=preregistration,
		)
		return cls(**values)

	def to_dict(self) -> dict[str, Any]:
		payload = self.preregistration_payload()
		payload.update({
			"schema_version": self.schema_version, "experiment_id": self.experiment_id,
			"hypothesis_id": self.hypothesis_id, "status": self.status.value,
			"experiment_version": self.experiment_version,
		})
		return payload


@dataclass(frozen=True)
class RunAttemptV1:
	schema_version: str
	run_attempt_id: str
	experiment_id: str
	attempt_number: int
	code_hash: str
	environment_hash: str
	scheduler: str
	scheduler_job_id: Optional[str]
	resources: Mapping[str, Any]
	timeout_seconds: int
	stdout_artifact: Optional[str]
	stderr_artifact: Optional[str]
	result_artifacts: tuple[str, ...]
	exit_code: Optional[int]
	failure_type: Optional[str]
	started_at: Optional[str]
	completed_at: Optional[str]
	status: RunAttemptStatus

	def __post_init__(self) -> None:
		for name in ("schema_version", "run_attempt_id", "experiment_id", "code_hash", "environment_hash", "scheduler"):
			object.__setattr__(self, name, _required(getattr(self, name), name))
		if not isinstance(self.attempt_number, int) or isinstance(self.attempt_number, bool) or self.attempt_number < 1:
			raise ValueError("attempt_number must be a positive integer")
		if not isinstance(self.timeout_seconds, int) or isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
			raise ValueError("timeout_seconds must be a positive integer")
		if self.exit_code is not None and (not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool)):
			raise ValueError("exit_code must be an integer or None")
		for name in ("scheduler_job_id", "stdout_artifact", "stderr_artifact", "failure_type"):
			object.__setattr__(self, name, _optional_string(getattr(self, name), name))
		if not isinstance(self.resources, Mapping):
			raise ValueError("resources must be a mapping")
		object.__setattr__(self, "resources", _freeze(self.resources))
		object.__setattr__(self, "result_artifacts", normalize_identity_ids(self.result_artifacts, "result_artifacts"))
		object.__setattr__(self, "started_at", _utc_iso(self.started_at, "started_at", optional=True))
		object.__setattr__(self, "completed_at", _utc_iso(self.completed_at, "completed_at", optional=True))
		object.__setattr__(self, "status", _enum(self.status, RunAttemptStatus, "run attempt status"))
		if self.started_at and self.completed_at:
			start = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
			end = datetime.fromisoformat(self.completed_at.replace("Z", "+00:00"))
			if end < start:
				raise ValueError("completed_at cannot precede started_at")
		expected = make_run_attempt_id(
			experiment_id=self.experiment_id, attempt_number=self.attempt_number,
			code_hash=self.code_hash, environment_hash=self.environment_hash,
		)
		if self.run_attempt_id != expected:
			raise ValueError("run_attempt_id does not match immutable attempt inputs")

	@classmethod
	def create(cls, **values: Any) -> "RunAttemptV1":
		values = dict(values)
		values.setdefault("schema_version", "run_attempt_v1")
		values.setdefault("scheduler_job_id", None)
		values.setdefault("resources", {})
		values.setdefault("stdout_artifact", None)
		values.setdefault("stderr_artifact", None)
		values.setdefault("result_artifacts", ())
		values.setdefault("exit_code", None)
		values.setdefault("failure_type", None)
		values.setdefault("started_at", None)
		values.setdefault("completed_at", None)
		values.setdefault("status", RunAttemptStatus.CREATED)
		values["run_attempt_id"] = make_run_attempt_id(
			experiment_id=values["experiment_id"], attempt_number=values["attempt_number"],
			code_hash=values["code_hash"], environment_hash=values["environment_hash"],
		)
		return cls(**values)

	def to_dict(self) -> dict[str, Any]:
		return {
			"schema_version": self.schema_version, "run_attempt_id": self.run_attempt_id,
			"experiment_id": self.experiment_id, "attempt_number": self.attempt_number,
			"code_hash": self.code_hash, "environment_hash": self.environment_hash,
			"scheduler": self.scheduler, "scheduler_job_id": self.scheduler_job_id,
			"resources": _thaw(self.resources), "timeout_seconds": self.timeout_seconds,
			"stdout_artifact": self.stdout_artifact, "stderr_artifact": self.stderr_artifact,
			"result_artifacts": list(self.result_artifacts), "exit_code": self.exit_code,
			"failure_type": self.failure_type, "started_at": self.started_at,
			"completed_at": self.completed_at, "status": self.status.value,
		}


@dataclass(frozen=True)
class ExperimentReviewV1:
	schema_version: str
	review_id: str
	experiment_id: str
	run_attempt_id: str
	primary_metric_name: str
	primary_metric_value: Optional[float]
	acceptance_rule: str
	verdict: ScientificVerdict
	reason_codes: tuple[str, ...]
	metrics_content_hash: str
	reviewer_revision: str
	reviewed_at: str

	def __post_init__(self) -> None:
		for name in (
			"schema_version", "review_id", "experiment_id", "run_attempt_id",
			"primary_metric_name", "acceptance_rule", "metrics_content_hash",
			"reviewer_revision",
		):
			object.__setattr__(self, name, _required(getattr(self, name), name))
		value = self.primary_metric_value
		if value is not None:
			if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
				raise ValueError("primary_metric_value must be finite or None")
			object.__setattr__(self, "primary_metric_value", float(value))
		object.__setattr__(self, "verdict", _enum(self.verdict, ScientificVerdict, "scientific verdict"))
		object.__setattr__(self, "reason_codes", normalize_identity_ids(self.reason_codes, "reason_codes"))
		if not self.reason_codes:
			raise ValueError("reason_codes must be non-empty")
		if self.verdict != ScientificVerdict.INCONCLUSIVE and self.primary_metric_value is None:
			raise ValueError("supported or refuted review requires a primary metric value")
		object.__setattr__(self, "reviewed_at", _utc_iso(self.reviewed_at, "reviewed_at"))
		expected = make_experiment_review_id(
			experiment_id=self.experiment_id, run_attempt_id=self.run_attempt_id,
			verdict=self.verdict.value, primary_metric_name=self.primary_metric_name,
			primary_metric_value=self.primary_metric_value, acceptance_rule=self.acceptance_rule,
			reason_codes=self.reason_codes, metrics_content_hash=self.metrics_content_hash,
			reviewer_revision=self.reviewer_revision,
		)
		if self.review_id != expected:
			raise ValueError("review_id does not match immutable scientific review inputs")

	@classmethod
	def create(cls, **values: Any) -> "ExperimentReviewV1":
		values = dict(values)
		values.setdefault("schema_version", "experiment_review_v1")
		verdict = _enum(values["verdict"], ScientificVerdict, "scientific verdict")
		values["review_id"] = make_experiment_review_id(
			experiment_id=values["experiment_id"], run_attempt_id=values["run_attempt_id"],
			verdict=verdict.value, primary_metric_name=values["primary_metric_name"],
			primary_metric_value=values.get("primary_metric_value"),
			acceptance_rule=values["acceptance_rule"],
			reason_codes=values["reason_codes"],
			metrics_content_hash=values["metrics_content_hash"],
			reviewer_revision=values["reviewer_revision"],
		)
		return cls(**values)

	def to_dict(self) -> dict[str, Any]:
		return {
			"schema_version": self.schema_version, "review_id": self.review_id,
			"experiment_id": self.experiment_id, "run_attempt_id": self.run_attempt_id,
			"primary_metric_name": self.primary_metric_name,
			"primary_metric_value": self.primary_metric_value,
			"acceptance_rule": self.acceptance_rule, "verdict": self.verdict.value,
			"reason_codes": list(self.reason_codes),
			"metrics_content_hash": self.metrics_content_hash,
			"reviewer_revision": self.reviewer_revision, "reviewed_at": self.reviewed_at,
		}


@dataclass(frozen=True)
class GateDecision:
	status: GateStatus
	reason_codes: tuple[str, ...]
	details: Mapping[str, Any]
	research_run_id: Optional[str]
	missing_paper_ids: tuple[str, ...] = ()
	missing_evidence_ids: tuple[str, ...] = ()

	def __post_init__(self) -> None:
		object.__setattr__(self, "status", _enum(self.status, GateStatus, "gate status"))
		object.__setattr__(self, "reason_codes", normalize_identity_ids(self.reason_codes, "reason_codes"))
		if not self.reason_codes:
			raise ValueError("reason_codes must be non-empty")
		if not isinstance(self.details, Mapping):
			raise ValueError("details must be a mapping")
		object.__setattr__(self, "details", _freeze(self.details))
		object.__setattr__(self, "research_run_id", _optional_string(self.research_run_id, "research_run_id"))
		object.__setattr__(self, "missing_paper_ids", normalize_identity_ids(self.missing_paper_ids, "missing_paper_ids"))
		object.__setattr__(self, "missing_evidence_ids", normalize_identity_ids(self.missing_evidence_ids, "missing_evidence_ids"))

	def to_dict(self) -> dict[str, Any]:
		return {
			"status": self.status.value, "reason_codes": list(self.reason_codes),
			"details": _thaw(self.details), "research_run_id": self.research_run_id,
			"missing_paper_ids": list(self.missing_paper_ids),
			"missing_evidence_ids": list(self.missing_evidence_ids),
		}


@dataclass(frozen=True)
class DecisionRecord:
	decision: StructuredDecision
	reason_code: str

	def __post_init__(self) -> None:
		object.__setattr__(self, "decision", _enum(self.decision, StructuredDecision, "structured decision"))
		object.__setattr__(self, "reason_code", _required(self.reason_code, "reason_code"))

	def to_dict(self) -> dict[str, str]:
		return {"decision": self.decision.value, "reason_code": self.reason_code}


__all__ = [
	"DecisionRecord",
	"ExperimentNodeV1",
	"ExperimentReviewV1",
	"GateDecision",
	"GraphResearchContext",
	"HypothesisNodeV1",
	"RunAttemptV1",
]
