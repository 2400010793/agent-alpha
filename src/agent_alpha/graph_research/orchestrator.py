from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Optional

from .budget import BudgetDecision, BudgetLedger, BudgetSpec, BudgetUsage
from .checkpoint import ResearchCheckpointStore
from .events import ResearchEvent
from .graph_gate import GraphResearchGate
from .ids import NO_EVIDENCE, deterministic_id, sha256_content_hash
from .models import (
	DecisionRecord,
	ExperimentNodeV1,
	ExperimentReviewV1,
	GateDecision,
	GraphResearchContext,
	HypothesisNodeV1,
	RunAttemptV1,
)
from .ports import (
	Clock,
	EvidenceProvider,
	EvidenceRecord,
	ExperimentExecutor,
	ExperimentPlanner,
	ExperimentReviewer,
	ExperimentReviewResult,
	HumanApprovalPort,
	HypothesisModel,
	MetricRecord,
	MetricRegistry,
)
from .state_machine import (
	ExperimentStateMachine,
	HypothesisStateMachine,
	ResearchRunStateMachine,
)
from .states import (
	ExperimentStatus,
	GateStatus,
	HypothesisStatus,
	OperationType,
	ResearchRunStatus,
	RunAttemptStatus,
	ScientificVerdict,
	StructuredDecision,
)


@dataclass(frozen=True)
class ResearchRunSnapshot:
	research_run_id: str
	run_status: ResearchRunStatus
	gate_decision: Mapping[str, Any]
	context: Mapping[str, Any]
	graph_input_hash: str
	paper_ids: tuple[str, ...]
	expected_evidence: Mapping[str, Mapping[str, str]]
	evidence: tuple[Mapping[str, Any], ...]
	hypotheses: Mapping[str, Mapping[str, Any]]
	hypothesis_statuses: Mapping[str, HypothesisStatus]
	hypothesis_decisions: Mapping[str, Mapping[str, Any]]
	experiments: Mapping[str, Mapping[str, Any]]
	experiment_statuses: Mapping[str, ExperimentStatus]
	planned_hypothesis_ids: tuple[str, ...]
	attempts: tuple[Mapping[str, Any], ...]
	pending_attempts: Mapping[str, Mapping[str, Any]]
	execution_errors: tuple[Mapping[str, Any], ...]
	pending_execution_errors: Mapping[str, Mapping[str, Any]]
	experiment_reviews: Mapping[str, Mapping[str, Any]]
	review_metrics: Mapping[str, tuple[Mapping[str, Any], ...]]
	registered_metric_keys: tuple[str, ...]
	committed_review_ids: tuple[str, ...]
	budget_spec: BudgetSpec
	budget_usage: BudgetUsage
	event_count: int


@dataclass(frozen=True)
class IntakeResult:
	gate_decision: GateDecision
	snapshot: Optional[ResearchRunSnapshot]


def _budget_spec_from_mapping(payload: Mapping[str, Any]) -> BudgetSpec:
	fields = {
		"max_hypotheses_per_graph", "max_primary_candidates_per_hypothesis",
		"max_refine_or_pivot_rounds", "max_attempts_per_experiment",
		"max_total_attempts", "max_compute_minutes", "max_llm_calls",
		"max_llm_tokens", "schema_version",
	}
	return BudgetSpec(**{name: payload[name] for name in fields if name in payload})


def _evidence_to_dict(record: EvidenceRecord) -> dict[str, str]:
	return {
		"evidence_id": record.evidence_id,
		"canonical_paper_id": record.canonical_paper_id,
		"content_hash": record.content_hash,
		"text": record.text,
	}


class GraphResearchOrchestrator:
	"""Offline graph-research orchestrator through experiment review handoff.

	All externally visible progress is represented by immutable events. Replaying
	the checkpoint reconstructs state and budget usage without invoking a port.
	"""

	def __init__(
		self,
		*,
		checkpoint_store: ResearchCheckpointStore,
		evidence_provider: EvidenceProvider | None = None,
		hypothesis_model: HypothesisModel | None = None,
		approval_port: HumanApprovalPort | None = None,
		experiment_planner: ExperimentPlanner | None = None,
		experiment_executor: ExperimentExecutor | None = None,
		experiment_reviewer: ExperimentReviewer | None = None,
		metric_registry: MetricRegistry | None = None,
		completed_run_lookup: Any | None = None,
		clock: Clock | None = None,
	) -> None:
		self.checkpoints = checkpoint_store
		self.evidence_provider = evidence_provider
		self.hypothesis_model = hypothesis_model
		self.approval_port = approval_port
		self.experiment_planner = experiment_planner
		self.experiment_executor = experiment_executor
		self.experiment_reviewer = experiment_reviewer
		self.metric_registry = metric_registry
		self.gate = GraphResearchGate(completed_run_lookup)
		self.clock = clock

	def start(
		self,
		graph: Mapping[str, Any],
		*,
		budget_spec: BudgetSpec,
		research_config_hash: str | None = None,
		completed_run_ids: Iterable[str] = (),
	) -> IntakeResult:
		decision = self.gate.evaluate(
			graph, research_config_hash=research_config_hash,
			completed_run_ids=completed_run_ids,
		)
		if decision.status == GateStatus.REJECTED:
			return IntakeResult(decision, None)
		if not decision.research_run_id:
			raise ValueError("non-rejected gate decision must include research_run_id")

		run_id = decision.research_run_id
		evidence_spans = graph.get("evidence_spans", graph.get("evidence", ()))
		valid_spans = [dict(item) for item in evidence_spans if isinstance(item, Mapping)] if isinstance(evidence_spans, (list, tuple)) else []
		evidence_hash = str(graph.get("evidence_content_hash") or "")
		if not evidence_hash:
			evidence_hash = sha256_content_hash(valid_spans) if valid_spans else NO_EVIDENCE
		bundle_id = str(graph.get("evidence_bundle_id") or deterministic_id(
			"ebundle", {"graph_artifact_id": graph.get("graph_artifact_id"), "evidence_content_hash": evidence_hash},
		))
		context = GraphResearchContext.create(
			graph_id=str(graph.get("graph_id") or ""),
			graph_version=str(graph.get("graph_version") or ""),
			graph_artifact_id=str(graph.get("graph_artifact_id") or ""),
			graph_content_hash=str(graph.get("graph_content_hash") or graph.get("content_hash") or ""),
			evidence_bundle_id=bundle_id,
			evidence_content_hash=evidence_hash,
			research_config_hash=str(research_config_hash or graph.get("research_config_hash") or graph.get("config_hash") or ""),
			snapshot_id=str(graph.get("snapshot_id") or graph.get("source_snapshot_id") or graph.get("as_of_date") or ""),
			producer_revision=str(graph.get("producer_revision") or ""),
			created_at=self._now_iso(),
		)
		if context.research_run_id != run_id:
			raise ValueError("gate and context produced different research_run_ids")
		graph_input_hash = sha256_content_hash(graph)
		if self.checkpoints.exists(run_id):
			snapshot = self.snapshot(run_id)
			if snapshot.graph_input_hash != graph_input_hash or snapshot.context["research_run_id"] != context.research_run_id:
				raise ValueError("existing checkpoint does not match immutable graph input")
			if snapshot.budget_spec != budget_spec:
				raise ValueError("existing checkpoint does not match immutable budget spec")
			return IntakeResult(decision, snapshot)

		paper_ids = sorted({
			str(node.get("canonical_paper_id"))
			for node in graph.get("paper_nodes", ()) if isinstance(node, Mapping) and node.get("canonical_paper_id")
		})
		expected_evidence = {
			str(item.get("evidence_id")): {
				"canonical_paper_id": str(item.get("canonical_paper_id") or item.get("paper_id") or ""),
				"content_hash": str(item.get("content_hash") or ""),
			}
			for item in valid_spans if item.get("evidence_id")
		}
		self._append(
			run_id,
			"run_initialized",
			{
				"context": context.to_dict(), "gate_decision": decision.to_dict(),
				"graph_input_hash": graph_input_hash, "paper_ids": paper_ids,
				"expected_evidence": expected_evidence,
				"budget_spec": budget_spec.to_dict(), "run_status": ResearchRunStatus.CREATED.value,
			},
		)
		self._transition_run(run_id, ResearchRunStatus.VALIDATED, "graph_gate_passed")
		if decision.status == GateStatus.NEEDS_DIGEST:
			self._transition_run(run_id, ResearchRunStatus.PAUSED_EVIDENCE, "digest_evidence_required")
		else:
			self._transition_run(run_id, ResearchRunStatus.EVIDENCE_READY, decision.status.value)
		return IntakeResult(decision, self.snapshot(run_id))

	def prepare_hypotheses(self, research_run_id: str) -> ResearchRunSnapshot:
		snapshot = self.snapshot(research_run_id)
		if snapshot.run_status in {
			ResearchRunStatus.PAUSED_EVIDENCE, ResearchRunStatus.PAUSED_BUDGET,
			ResearchRunStatus.FAILED_FINAL,
		}:
			return snapshot
		if snapshot.run_status not in {
			ResearchRunStatus.EVIDENCE_READY, ResearchRunStatus.HYPOTHESES_READY,
			ResearchRunStatus.APPROVAL_PENDING,
		}:
			raise ValueError(f"hypothesis preparation is not valid from {snapshot.run_status.value}")

		if snapshot.run_status == ResearchRunStatus.EVIDENCE_READY and not snapshot.hypotheses:
			evidence = snapshot.evidence
			gate_status = GateStatus(str(snapshot.gate_decision["status"]))
			if not evidence and gate_status != GateStatus.STRUCTURAL_ONLY:
				if self.evidence_provider is None:
					raise RuntimeError("EvidenceProvider is required for eligible graph research")
				loaded = self.evidence_provider.get_evidence(
					str(snapshot.context["graph_id"]), str(snapshot.context["graph_version"]), snapshot.paper_ids,
				)
				self._validate_evidence(loaded, snapshot.paper_ids, snapshot.expected_evidence)
				self._append(research_run_id, "evidence_loaded", {"records": [_evidence_to_dict(item) for item in loaded]})
				snapshot = self.snapshot(research_run_id)
				if not snapshot.evidence:
					self._transition_run(research_run_id, ResearchRunStatus.PAUSED_EVIDENCE, "evidence_provider_returned_no_records")
					return self.snapshot(research_run_id)

			llm_budget = self._consume_budget(
				research_run_id, f"hypothesis_model:{research_run_id}:1", BudgetUsage(llm_calls=1),
			)
			if not llm_budget.allowed:
				self._transition_run(research_run_id, ResearchRunStatus.PAUSED_BUDGET, llm_budget.reason_codes[0])
				return self.snapshot(research_run_id)
			if self.hypothesis_model is None:
				raise RuntimeError("HypothesisModel is required for hypothesis preparation")
			evidence_records = tuple(EvidenceRecord(**dict(record)) for record in snapshot.evidence)
			hypotheses = self.hypothesis_model.propose(research_run_id, evidence_records)
			self._validate_hypotheses(hypotheses, snapshot)
			if hypotheses:
				hypothesis_budget = self._consume_budget(
					research_run_id, f"hypotheses:{research_run_id}:1",
					BudgetUsage(hypotheses=len(hypotheses)),
				)
				if not hypothesis_budget.allowed:
					self._transition_run(research_run_id, ResearchRunStatus.PAUSED_BUDGET, hypothesis_budget.reason_codes[0])
					return self.snapshot(research_run_id)
			self._append(research_run_id, "hypotheses_proposed", {"hypotheses": [item.to_dict() for item in hypotheses]})
			self._transition_run(research_run_id, ResearchRunStatus.HYPOTHESES_READY, "hypothesis_generation_complete")
			snapshot = self.snapshot(research_run_id)

		if snapshot.run_status == ResearchRunStatus.HYPOTHESES_READY:
			if not snapshot.hypotheses:
				self._transition_run(research_run_id, ResearchRunStatus.FAILED_FINAL, "no_hypotheses_proposed")
				return self.snapshot(research_run_id)
			self._transition_run(research_run_id, ResearchRunStatus.APPROVAL_PENDING, "hypotheses_ready_for_review")
			snapshot = self.snapshot(research_run_id)

		if snapshot.run_status == ResearchRunStatus.APPROVAL_PENDING:
			if self.approval_port is None:
				raise RuntimeError("HumanApprovalPort is required for hypothesis approval")
			for hypothesis_id in sorted(snapshot.hypotheses):
				snapshot = self.snapshot(research_run_id)
				status = snapshot.hypothesis_statuses[hypothesis_id]
				if status == HypothesisStatus.PROPOSED:
					self._transition_hypothesis(research_run_id, hypothesis_id, HypothesisStatus.EVIDENCE_CHECKED, "evidence_refs_validated")
					snapshot = self.snapshot(research_run_id)
				decision_payload = snapshot.hypothesis_decisions.get(hypothesis_id)
				if decision_payload is None:
					hypothesis = HypothesisNodeV1.create(**{
						key: value for key, value in snapshot.hypotheses[hypothesis_id].items()
						if key not in {"hypothesis_id", "schema_version"}
					})
					decision = self.approval_port.review(hypothesis)
					if not isinstance(decision, DecisionRecord):
						raise TypeError("HumanApprovalPort.review must return DecisionRecord")
					if decision.decision not in {
						StructuredDecision.PROCEED, StructuredDecision.REJECT,
						StructuredDecision.PAUSE_EVIDENCE,
					}:
						raise ValueError(f"unsupported hypothesis approval decision: {decision.decision.value}")
					self._append(research_run_id, "hypothesis_decided", {"hypothesis_id": hypothesis_id, **decision.to_dict()})
					decision_payload = decision.to_dict()
				decision_type = StructuredDecision(str(decision_payload["decision"]))
				if decision_type == StructuredDecision.PROCEED:
					if self.snapshot(research_run_id).hypothesis_statuses[hypothesis_id] == HypothesisStatus.EVIDENCE_CHECKED:
						self._transition_hypothesis(research_run_id, hypothesis_id, HypothesisStatus.APPROVED, str(decision_payload["reason_code"]))
				elif decision_type == StructuredDecision.REJECT:
					if self.snapshot(research_run_id).hypothesis_statuses[hypothesis_id] == HypothesisStatus.EVIDENCE_CHECKED:
						self._transition_hypothesis(research_run_id, hypothesis_id, HypothesisStatus.ABANDONED, str(decision_payload["reason_code"]))
				else:
					self._transition_run(research_run_id, ResearchRunStatus.PAUSED_EVIDENCE, str(decision_payload["reason_code"]))
					return self.snapshot(research_run_id)

			snapshot = self.snapshot(research_run_id)
			if not any(status == HypothesisStatus.APPROVED for status in snapshot.hypothesis_statuses.values()):
				self._transition_run(research_run_id, ResearchRunStatus.FAILED_FINAL, "all_hypotheses_rejected")
		return self.snapshot(research_run_id)

	def plan_experiments(self, research_run_id: str) -> ResearchRunSnapshot:
		"""Create and preregister experiments for every approved hypothesis."""
		snapshot = self.snapshot(research_run_id)
		if snapshot.run_status in {
			ResearchRunStatus.EXPERIMENTS_QUEUED, ResearchRunStatus.RUNNING,
			ResearchRunStatus.REVIEW_PENDING, ResearchRunStatus.COMPLETED,
			ResearchRunStatus.PAUSED_BUDGET, ResearchRunStatus.FAILED_FINAL,
		}:
			return snapshot
		if snapshot.run_status != ResearchRunStatus.APPROVAL_PENDING:
			raise ValueError(f"experiment planning is not valid from {snapshot.run_status.value}")
		if self.experiment_planner is None:
			raise RuntimeError("ExperimentPlanner is required for experiment planning")

		approved_ids = sorted(
			hypothesis_id for hypothesis_id, status in snapshot.hypothesis_statuses.items()
			if status in {HypothesisStatus.APPROVED, HypothesisStatus.TESTING}
		)
		if not approved_ids:
			self._transition_run(research_run_id, ResearchRunStatus.FAILED_FINAL, "no_approved_hypotheses")
			return self.snapshot(research_run_id)

		for hypothesis_id in approved_ids:
			snapshot = self.snapshot(research_run_id)
			if hypothesis_id in snapshot.planned_hypothesis_ids:
				continue
			llm_budget = self._consume_budget(
				research_run_id, f"experiment_planner:{hypothesis_id}:1",
				BudgetUsage(llm_calls=1), hypothesis_id=hypothesis_id,
			)
			if not llm_budget.allowed:
				self._transition_run(research_run_id, ResearchRunStatus.PAUSED_BUDGET, llm_budget.reason_codes[0])
				return self.snapshot(research_run_id)
			hypothesis = self._hypothesis_node(snapshot, hypothesis_id)
			experiments = self.experiment_planner.plan(hypothesis, snapshot.budget_spec.budget_id)
			self._validate_experiments(experiments, snapshot, hypothesis_id)
			primary_count = sum(item.operation_type == OperationType.PRIMARY_TEST for item in experiments)
			if primary_count:
				candidate_budget = self._consume_budget(
					research_run_id, f"primary_candidates:{hypothesis_id}:1",
					BudgetUsage(primary_candidates=primary_count), hypothesis_id=hypothesis_id,
				)
				if not candidate_budget.allowed:
					self._transition_run(research_run_id, ResearchRunStatus.PAUSED_BUDGET, candidate_budget.reason_codes[0])
					return self.snapshot(research_run_id)
			self._append(research_run_id, "experiments_planned", {
				"hypothesis_id": hypothesis_id,
				"experiments": [item.to_dict() for item in experiments],
			})

		snapshot = self.snapshot(research_run_id)
		for hypothesis_id in approved_ids:
			if not any(
				str(experiment["hypothesis_id"]) == hypothesis_id
				for experiment in snapshot.experiments.values()
			):
				self._transition_run(research_run_id, ResearchRunStatus.FAILED_FINAL, "planner_returned_no_experiments")
				return self.snapshot(research_run_id)

		for experiment_id in sorted(snapshot.experiments):
			status = self.snapshot(research_run_id).experiment_statuses[experiment_id]
			if status == ExperimentStatus.CREATED:
				self._transition_experiment(research_run_id, experiment_id, ExperimentStatus.PREREGISTERED, "immutable_preregistration_recorded")
				status = ExperimentStatus.PREREGISTERED
			if status == ExperimentStatus.PREREGISTERED:
				self._transition_experiment(research_run_id, experiment_id, ExperimentStatus.QUEUED, "experiment_ready_for_execution")
		for hypothesis_id in approved_ids:
			if self.snapshot(research_run_id).hypothesis_statuses[hypothesis_id] == HypothesisStatus.APPROVED:
				self._transition_hypothesis(research_run_id, hypothesis_id, HypothesisStatus.TESTING, "experiments_preregistered")
		self._transition_run(research_run_id, ResearchRunStatus.EXPERIMENTS_QUEUED, "approved_experiments_preregistered")
		return self.snapshot(research_run_id)

	def execute_experiments(self, research_run_id: str) -> ResearchRunSnapshot:
		"""Execute queued experiments, retry infrastructure failures, and stop for review."""
		snapshot = self.snapshot(research_run_id)
		if snapshot.run_status in {
			ResearchRunStatus.REVIEW_PENDING, ResearchRunStatus.COMPLETED,
			ResearchRunStatus.PAUSED_BUDGET, ResearchRunStatus.FAILED_FINAL,
		}:
			return snapshot
		if self.experiment_executor is None:
			raise RuntimeError("ExperimentExecutor is required for experiment execution")
		if snapshot.run_status == ResearchRunStatus.FAILED_RETRYABLE:
			self._transition_run(research_run_id, ResearchRunStatus.EXPERIMENTS_QUEUED, "resume_retryable_execution")
			snapshot = self.snapshot(research_run_id)
		if snapshot.run_status == ResearchRunStatus.EXPERIMENTS_QUEUED:
			self._transition_run(research_run_id, ResearchRunStatus.RUNNING, "experiment_execution_started")
			snapshot = self.snapshot(research_run_id)
		if snapshot.run_status != ResearchRunStatus.RUNNING:
			raise ValueError(f"experiment execution is not valid from {snapshot.run_status.value}")
		for experiment_id in sorted(snapshot.experiments):
			while True:
				snapshot = self.snapshot(research_run_id)
				status = snapshot.experiment_statuses[experiment_id]
				if status in {ExperimentStatus.REVIEW_PENDING, ExperimentStatus.FAILED_FINAL, ExperimentStatus.COMPLETED}:
					break
				attempts = self._attempts_for(snapshot, experiment_id)
				pending_attempt = snapshot.pending_attempts.get(experiment_id)
				if status == ExperimentStatus.RUNNING and pending_attempt is not None:
					self._apply_attempt_outcome(research_run_id, RunAttemptV1(**dict(pending_attempt)))
					continue
				if status == ExperimentStatus.RUNNING and experiment_id in snapshot.pending_execution_errors:
					self._transition_experiment(research_run_id, experiment_id, ExperimentStatus.FAILED_FINAL, "executor_contract_failure")
					break
				if status == ExperimentStatus.FAILED_RETRYABLE:
					if len(attempts) >= snapshot.budget_spec.max_attempts_per_experiment:
						self._transition_experiment(research_run_id, experiment_id, ExperimentStatus.FAILED_FINAL, "attempt_limit_reached")
						break
					self._transition_experiment(research_run_id, experiment_id, ExperimentStatus.QUEUED, "retry_infrastructure_failure")
					status = ExperimentStatus.QUEUED
				if status == ExperimentStatus.QUEUED:
					self._transition_experiment(research_run_id, experiment_id, ExperimentStatus.RUNNING, "executor_invoked")
					status = ExperimentStatus.RUNNING
				if status != ExperimentStatus.RUNNING:
					raise ValueError(f"experiment {experiment_id} cannot execute from {status.value}")

				snapshot = self.snapshot(research_run_id)
				attempt_number = len(self._attempts_for(snapshot, experiment_id)) + 1
				experiment = self._experiment_node(snapshot, experiment_id)
				reserved_minutes = self._reserved_compute_minutes(experiment)
				attempt_budget = self._consume_budget(
					research_run_id, f"run_attempt:{experiment_id}:{attempt_number}",
					BudgetUsage(attempts=1, compute_minutes=reserved_minutes),
					hypothesis_id=experiment.hypothesis_id, experiment_id=experiment_id,
				)
				if not attempt_budget.allowed:
					self._transition_run(research_run_id, ResearchRunStatus.PAUSED_BUDGET, attempt_budget.reason_codes[0])
					return self.snapshot(research_run_id)
				try:
					attempt = self.experiment_executor.execute(experiment, attempt_number)
					self._validate_attempt(attempt, experiment_id, attempt_number, snapshot)
				except Exception as exc:
					self._append(research_run_id, "executor_failed", {
						"experiment_id": experiment_id, "attempt_number": attempt_number,
						"error_type": type(exc).__name__, "message": str(exc)[:500],
					})
					self._transition_experiment(research_run_id, experiment_id, ExperimentStatus.FAILED_FINAL, "executor_contract_failure")
					break
				self._append(research_run_id, "attempt_completed", {"attempt": attempt.to_dict()})
				self._apply_attempt_outcome(research_run_id, attempt)

		snapshot = self.snapshot(research_run_id)
		if any(status == ExperimentStatus.REVIEW_PENDING for status in snapshot.experiment_statuses.values()):
			self._transition_run(research_run_id, ResearchRunStatus.REVIEW_PENDING, "execution_artifacts_ready_for_review")
		elif snapshot.experiment_statuses and all(
			status == ExperimentStatus.FAILED_FINAL for status in snapshot.experiment_statuses.values()
		):
			self._transition_run(research_run_id, ResearchRunStatus.FAILED_FINAL, "all_experiments_failed")
		return self.snapshot(research_run_id)

	def review_experiments(self, research_run_id: str) -> ResearchRunSnapshot:
		"""Commit metrics and scientific verdicts without treating technical failure as refutation."""
		snapshot = self.snapshot(research_run_id)
		if snapshot.run_status in {
			ResearchRunStatus.COMPLETED, ResearchRunStatus.PAUSED_BUDGET,
			ResearchRunStatus.FAILED_FINAL,
		}:
			return snapshot
		if snapshot.run_status != ResearchRunStatus.REVIEW_PENDING:
			raise ValueError(f"scientific review is not valid from {snapshot.run_status.value}")
		if self.experiment_reviewer is None:
			raise RuntimeError("ExperimentReviewer is required for scientific review")
		if self.metric_registry is None:
			raise RuntimeError("MetricRegistry is required for scientific review")

		for experiment_id in sorted(snapshot.experiments):
			snapshot = self.snapshot(research_run_id)
			if snapshot.experiment_statuses[experiment_id] != ExperimentStatus.REVIEW_PENDING:
				continue
			experiment = self._experiment_node(snapshot, experiment_id)
			attempt = self._latest_successful_attempt(snapshot, experiment_id)
			if attempt is None:
				raise ValueError(f"review-pending experiment has no successful attempt: {experiment_id}")

			prepared = snapshot.experiment_reviews.get(experiment_id)
			if prepared is None:
				review_budget = self._consume_budget(
					research_run_id, f"experiment_reviewer:{experiment_id}:{attempt.run_attempt_id}",
					BudgetUsage(llm_calls=1), hypothesis_id=experiment.hypothesis_id,
					experiment_id=experiment_id,
				)
				if not review_budget.allowed:
					self._transition_run(research_run_id, ResearchRunStatus.PAUSED_BUDGET, review_budget.reason_codes[0])
					return self.snapshot(research_run_id)
				result = self.experiment_reviewer.review(experiment, attempt)
				self._validate_review_result(result, experiment, attempt)
				self._append(research_run_id, "experiment_review_prepared", {
					"review": result.review.to_dict(),
					"metrics": [metric.to_dict() for metric in result.metrics],
				})
				snapshot = self.snapshot(research_run_id)

			review = ExperimentReviewV1(**dict(snapshot.experiment_reviews[experiment_id]))
			metrics = tuple(MetricRecord(**dict(item)) for item in snapshot.review_metrics[experiment_id])
			for metric in metrics:
				snapshot = self.snapshot(research_run_id)
				if metric.registry_key in snapshot.registered_metric_keys:
					continue
				registered = self.metric_registry.register(metric)
				if not isinstance(registered, MetricRecord) or registered != metric:
					raise ValueError("MetricRegistry.register must return the identical MetricRecord")
				self._append(research_run_id, "metric_registered", {
					"registry_key": metric.registry_key, "metric": metric.to_dict(),
				})
			snapshot = self.snapshot(research_run_id)
			if review.review_id not in snapshot.committed_review_ids:
				self._append(research_run_id, "experiment_review_committed", {
					"experiment_id": experiment_id, "review_id": review.review_id,
				})
			self._transition_experiment(
				research_run_id, experiment_id, ExperimentStatus.COMPLETED,
				"scientific_review_committed",
			)

		snapshot = self.snapshot(research_run_id)
		for hypothesis_id, status in sorted(snapshot.hypothesis_statuses.items()):
			if status != HypothesisStatus.TESTING:
				continue
			target = self._aggregate_hypothesis_verdict(snapshot, hypothesis_id)
			if target is not None:
				self._transition_hypothesis(
					research_run_id, hypothesis_id, target,
					"experiment_verdicts_aggregated",
				)
		snapshot = self.snapshot(research_run_id)
		if all(
			status in {ExperimentStatus.COMPLETED, ExperimentStatus.FAILED_FINAL}
			for status in snapshot.experiment_statuses.values()
		) and not any(status == HypothesisStatus.TESTING for status in snapshot.hypothesis_statuses.values()):
			self._transition_run(research_run_id, ResearchRunStatus.COMPLETED, "scientific_review_complete")
		return self.snapshot(research_run_id)

	def snapshot(self, research_run_id: str) -> ResearchRunSnapshot:
		events = self.checkpoints.load(research_run_id)
		if not events:
			raise KeyError(f"unknown research run: {research_run_id}")
		initialized = events[0]
		if initialized.event_type != "run_initialized":
			raise ValueError("first research event must initialize the run")
		payload = initialized.payload
		run_machine = ResearchRunStateMachine(ResearchRunStatus(str(payload["run_status"])))
		budget_spec = _budget_spec_from_mapping(payload["budget_spec"])  # type: ignore[arg-type]
		ledger = BudgetLedger(budget_spec)
		evidence: tuple[Mapping[str, Any], ...] = ()
		hypotheses: dict[str, Mapping[str, Any]] = {}
		hypothesis_statuses: dict[str, HypothesisStatus] = {}
		decisions: dict[str, Mapping[str, Any]] = {}
		experiments: dict[str, Mapping[str, Any]] = {}
		experiment_statuses: dict[str, ExperimentStatus] = {}
		planned_hypothesis_ids: set[str] = set()
		attempts: list[Mapping[str, Any]] = []
		pending_attempts: dict[str, Mapping[str, Any]] = {}
		execution_errors: list[Mapping[str, Any]] = []
		pending_execution_errors: dict[str, Mapping[str, Any]] = {}
		experiment_reviews: dict[str, Mapping[str, Any]] = {}
		review_metrics: dict[str, tuple[Mapping[str, Any], ...]] = {}
		registered_metric_keys: set[str] = set()
		committed_review_ids: set[str] = set()

		for event in events[1:]:
			item = event.payload
			if event.event_type == "run_transitioned":
				if run_machine.state.value != item["source"]:
					raise ValueError("run transition source does not match replayed state")
				run_machine.transition(ResearchRunStatus(str(item["target"])))
			elif event.event_type == "evidence_loaded":
				evidence = tuple(MappingProxyType(dict(record)) for record in item.get("records", ()))  # type: ignore[union-attr]
			elif event.event_type == "budget_consumed":
				usage = BudgetUsage(**dict(item["usage"]))  # type: ignore[arg-type]
				result = ledger.consume(
					str(item["budget_event_id"]), usage,
					hypothesis_id=item.get("hypothesis_id"), experiment_id=item.get("experiment_id"),
				)
				if not result.allowed:
					raise ValueError("checkpoint contains invalid budget consumption")
			elif event.event_type == "hypotheses_proposed":
				for raw in item.get("hypotheses", ()):  # type: ignore[union-attr]
					hypothesis_id = str(raw["hypothesis_id"])
					hypotheses[hypothesis_id] = MappingProxyType(dict(raw))
					hypothesis_statuses[hypothesis_id] = HypothesisStatus(str(raw["status"]))
			elif event.event_type == "hypothesis_transitioned":
				hypothesis_id = str(item["hypothesis_id"])
				machine = HypothesisStateMachine(hypothesis_statuses[hypothesis_id])
				if machine.state.value != item["source"]:
					raise ValueError("hypothesis transition source does not match replayed state")
				hypothesis_statuses[hypothesis_id] = machine.transition(HypothesisStatus(str(item["target"])))
			elif event.event_type == "hypothesis_decided":
				decisions[str(item["hypothesis_id"])] = MappingProxyType({
					"decision": item["decision"], "reason_code": item["reason_code"],
				})
			elif event.event_type == "experiments_planned":
				planned_hypothesis_ids.add(str(item["hypothesis_id"]))
				for raw in item.get("experiments", ()):  # type: ignore[union-attr]
					experiment_id = str(raw["experiment_id"])
					if experiment_id in experiments:
						raise ValueError(f"duplicate experiment in checkpoint: {experiment_id}")
					experiments[experiment_id] = MappingProxyType(dict(raw))
					experiment_statuses[experiment_id] = ExperimentStatus(str(raw["status"]))
			elif event.event_type == "experiment_transitioned":
				experiment_id = str(item["experiment_id"])
				machine = ExperimentStateMachine(experiment_statuses[experiment_id])
				if machine.state.value != item["source"]:
					raise ValueError("experiment transition source does not match replayed state")
				experiment_statuses[experiment_id] = machine.transition(ExperimentStatus(str(item["target"])))
				pending_attempts.pop(experiment_id, None)
				pending_execution_errors.pop(experiment_id, None)
			elif event.event_type == "attempt_completed":
				raw_attempt = MappingProxyType(dict(item["attempt"]))  # type: ignore[arg-type]
				attempts.append(raw_attempt)
				pending_attempts[str(raw_attempt["experiment_id"])] = raw_attempt
			elif event.event_type == "executor_failed":
				raw_error = MappingProxyType(dict(item))
				execution_errors.append(raw_error)
				pending_execution_errors[str(raw_error["experiment_id"])] = raw_error
			elif event.event_type == "experiment_review_prepared":
				raw_review = MappingProxyType(dict(item["review"]))  # type: ignore[arg-type]
				experiment_id = str(raw_review["experiment_id"])
				if experiment_id in experiment_reviews:
					raise ValueError(f"duplicate prepared review in checkpoint: {experiment_id}")
				experiment_reviews[experiment_id] = raw_review
				review_metrics[experiment_id] = tuple(
					MappingProxyType(dict(metric)) for metric in item.get("metrics", ())  # type: ignore[union-attr]
				)
			elif event.event_type == "metric_registered":
				registry_key = str(item["registry_key"])
				if registry_key in registered_metric_keys:
					raise ValueError(f"duplicate metric registration in checkpoint: {registry_key}")
				registered_metric_keys.add(registry_key)
			elif event.event_type == "experiment_review_committed":
				committed_review_ids.add(str(item["review_id"]))

		return ResearchRunSnapshot(
			research_run_id=research_run_id,
			run_status=run_machine.state,
			gate_decision=MappingProxyType(dict(payload["gate_decision"])),  # type: ignore[arg-type]
			context=MappingProxyType(dict(payload["context"])),  # type: ignore[arg-type]
			graph_input_hash=str(payload["graph_input_hash"]),
			paper_ids=tuple(str(item) for item in payload["paper_ids"]),  # type: ignore[index]
			expected_evidence=MappingProxyType({
				str(key): MappingProxyType(dict(value))
				for key, value in payload.get("expected_evidence", {}).items()  # type: ignore[union-attr]
			}),
			evidence=evidence,
			hypotheses=MappingProxyType(hypotheses),
			hypothesis_statuses=MappingProxyType(hypothesis_statuses),
			hypothesis_decisions=MappingProxyType(decisions),
			experiments=MappingProxyType(experiments),
			experiment_statuses=MappingProxyType(experiment_statuses),
			planned_hypothesis_ids=tuple(sorted(planned_hypothesis_ids)),
			attempts=tuple(attempts),
			pending_attempts=MappingProxyType(pending_attempts),
			execution_errors=tuple(execution_errors),
			pending_execution_errors=MappingProxyType(pending_execution_errors),
			experiment_reviews=MappingProxyType(experiment_reviews),
			review_metrics=MappingProxyType(review_metrics),
			registered_metric_keys=tuple(sorted(registered_metric_keys)),
			committed_review_ids=tuple(sorted(committed_review_ids)),
			budget_spec=budget_spec,
			budget_usage=ledger.usage,
			event_count=len(events),
		)

	def _consume_budget(
		self, research_run_id: str, budget_event_id: str, usage: BudgetUsage,
		*, hypothesis_id: str | None = None, experiment_id: str | None = None,
	) -> BudgetDecision:
		events = self.checkpoints.load(research_run_id)
		for event in events:
			if event.event_type not in {"budget_consumed", "budget_denied"}:
				continue
			if event.payload.get("budget_event_id") == budget_event_id:
				if event.event_type == "budget_consumed":
					return BudgetDecision(True, ("duplicate_event",), self.snapshot(research_run_id).budget_usage, idempotent_replay=True)
				return BudgetDecision(False, tuple(str(item) for item in event.payload["reason_codes"]), self.snapshot(research_run_id).budget_usage)
		snapshot = self.snapshot(research_run_id)
		ledger = BudgetLedger(snapshot.budget_spec)
		for event in events:
			if event.event_type == "budget_consumed":
				ledger.consume(
					str(event.payload["budget_event_id"]), BudgetUsage(**dict(event.payload["usage"])),  # type: ignore[arg-type]
					hypothesis_id=event.payload.get("hypothesis_id"), experiment_id=event.payload.get("experiment_id"),
				)
		decision = ledger.consume(
			budget_event_id, usage, hypothesis_id=hypothesis_id, experiment_id=experiment_id,
		)
		payload: dict[str, Any] = {
			"budget_event_id": budget_event_id, "usage": usage.to_dict(),
			"hypothesis_id": hypothesis_id, "experiment_id": experiment_id,
		}
		if decision.allowed:
			self._append(research_run_id, "budget_consumed", payload)
		else:
			payload["reason_codes"] = list(decision.reason_codes)
			self._append(research_run_id, "budget_denied", payload)
		return decision

	def _transition_run(self, research_run_id: str, target: ResearchRunStatus, reason_code: str) -> None:
		source = self.snapshot(research_run_id).run_status
		ResearchRunStateMachine(source).transition(target)
		self._append(research_run_id, "run_transitioned", {
			"source": source.value, "target": target.value, "reason_code": reason_code,
		})

	def _transition_hypothesis(
		self, research_run_id: str, hypothesis_id: str,
		target: HypothesisStatus, reason_code: str,
	) -> None:
		source = self.snapshot(research_run_id).hypothesis_statuses[hypothesis_id]
		HypothesisStateMachine(source).transition(target)
		self._append(research_run_id, "hypothesis_transitioned", {
			"hypothesis_id": hypothesis_id, "source": source.value,
			"target": target.value, "reason_code": reason_code,
		})

	def _transition_experiment(
		self, research_run_id: str, experiment_id: str,
		target: ExperimentStatus, reason_code: str,
	) -> None:
		source = self.snapshot(research_run_id).experiment_statuses[experiment_id]
		ExperimentStateMachine(source).transition(target)
		self._append(research_run_id, "experiment_transitioned", {
			"experiment_id": experiment_id, "source": source.value,
			"target": target.value, "reason_code": reason_code,
		})

	def _apply_attempt_outcome(self, research_run_id: str, attempt: RunAttemptV1) -> None:
		if attempt.status == RunAttemptStatus.SUCCEEDED:
			self._transition_experiment(
				research_run_id, attempt.experiment_id, ExperimentStatus.REVIEW_PENDING,
				"run_attempt_succeeded",
			)
			return
		if attempt.status == RunAttemptStatus.FAILED_FINAL:
			self._transition_experiment(
				research_run_id, attempt.experiment_id, ExperimentStatus.FAILED_FINAL,
				attempt.failure_type or "run_attempt_failed_final",
			)
			return
		self._transition_experiment(
			research_run_id, attempt.experiment_id, ExperimentStatus.FAILED_RETRYABLE,
			attempt.failure_type or attempt.status.value,
		)
		snapshot = self.snapshot(research_run_id)
		if len(self._attempts_for(snapshot, attempt.experiment_id)) >= snapshot.budget_spec.max_attempts_per_experiment:
			self._transition_experiment(
				research_run_id, attempt.experiment_id, ExperimentStatus.FAILED_FINAL,
				"attempt_limit_reached",
			)

	@staticmethod
	def _latest_successful_attempt(
		snapshot: ResearchRunSnapshot, experiment_id: str,
	) -> RunAttemptV1 | None:
		for raw in reversed(GraphResearchOrchestrator._attempts_for(snapshot, experiment_id)):
			attempt = RunAttemptV1(**dict(raw))
			if attempt.status == RunAttemptStatus.SUCCEEDED:
				return attempt
		return None

	@staticmethod
	def _aggregate_hypothesis_verdict(
		snapshot: ResearchRunSnapshot, hypothesis_id: str,
	) -> HypothesisStatus | None:
		experiment_ids = [
			experiment_id for experiment_id, experiment in snapshot.experiments.items()
			if experiment["hypothesis_id"] == hypothesis_id
		]
		if not experiment_ids:
			return HypothesisStatus.INCONCLUSIVE
		statuses = [snapshot.experiment_statuses[experiment_id] for experiment_id in experiment_ids]
		if any(status not in {ExperimentStatus.COMPLETED, ExperimentStatus.FAILED_FINAL} for status in statuses):
			return None
		# Infrastructure or adapter failure means the scientific test was incomplete,
		# never that the hypothesis was refuted.
		if any(status == ExperimentStatus.FAILED_FINAL for status in statuses):
			return HypothesisStatus.INCONCLUSIVE
		verdicts = [
			ScientificVerdict(str(snapshot.experiment_reviews[experiment_id]["verdict"]))
			for experiment_id in experiment_ids
		]
		if verdicts and all(verdict == ScientificVerdict.SUPPORTED for verdict in verdicts):
			return HypothesisStatus.SUPPORTED
		if verdicts and all(verdict == ScientificVerdict.REFUTED for verdict in verdicts):
			return HypothesisStatus.REFUTED
		return HypothesisStatus.INCONCLUSIVE

	def _append(self, research_run_id: str, event_type: str, payload: Mapping[str, Any]) -> ResearchEvent:
		events = self.checkpoints.load(research_run_id)
		event = ResearchEvent.create(
			research_run_id=research_run_id, sequence=len(events) + 1,
			event_type=event_type, payload=payload,
			previous_event_id=events[-1].event_id if events else "",
			created_at=self._now_iso(),
		)
		self.checkpoints.append(event)
		return event

	def _now_iso(self) -> str:
		value = self.clock.now() if self.clock is not None else datetime.now(timezone.utc)
		if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
			raise ValueError("Clock must return a timezone-aware UTC datetime")
		return value.isoformat()

	@staticmethod
	def _hypothesis_node(snapshot: ResearchRunSnapshot, hypothesis_id: str) -> HypothesisNodeV1:
		payload = {
			key: value for key, value in snapshot.hypotheses[hypothesis_id].items()
			if key not in {"hypothesis_id", "schema_version"}
		}
		payload["status"] = snapshot.hypothesis_statuses[hypothesis_id]
		return HypothesisNodeV1.create(**payload)

	@staticmethod
	def _experiment_node(snapshot: ResearchRunSnapshot, experiment_id: str) -> ExperimentNodeV1:
		payload = {
			key: value for key, value in snapshot.experiments[experiment_id].items()
			if key not in {"experiment_id", "schema_version"}
		}
		payload["status"] = snapshot.experiment_statuses[experiment_id]
		return ExperimentNodeV1.create(**payload)

	@staticmethod
	def _attempts_for(snapshot: ResearchRunSnapshot, experiment_id: str) -> tuple[Mapping[str, Any], ...]:
		return tuple(item for item in snapshot.attempts if item["experiment_id"] == experiment_id)

	@staticmethod
	def _reserved_compute_minutes(experiment: ExperimentNodeV1) -> float:
		value = experiment.cost_assumptions.get("reserved_compute_minutes", 0.0)
		if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
			raise ValueError("cost_assumptions.reserved_compute_minutes must be a non-negative number")
		return float(value)

	@staticmethod
	def _validate_evidence(
		records: tuple[EvidenceRecord, ...], paper_ids: tuple[str, ...],
		expected_evidence: Mapping[str, Mapping[str, str]],
	) -> None:
		seen: set[str] = set()
		allowed_papers = set(paper_ids)
		for record in records:
			if not isinstance(record, EvidenceRecord):
				raise TypeError("EvidenceProvider must return EvidenceRecord values")
			if not record.evidence_id or not record.content_hash or not record.text:
				raise ValueError("evidence records require ID, content hash, and text")
			if record.evidence_id in seen:
				raise ValueError(f"duplicate evidence_id: {record.evidence_id}")
			if record.canonical_paper_id not in allowed_papers:
				raise ValueError(f"evidence paper is outside graph: {record.canonical_paper_id}")
			expected = expected_evidence.get(record.evidence_id)
			if expected is None:
				raise ValueError(f"evidence was not declared by graph input: {record.evidence_id}")
			if record.canonical_paper_id != expected["canonical_paper_id"] or record.content_hash != expected["content_hash"]:
				raise ValueError(f"evidence identity or content hash mismatch: {record.evidence_id}")
			seen.add(record.evidence_id)
		if seen != set(expected_evidence):
			missing = sorted(set(expected_evidence) - seen)
			raise ValueError(f"EvidenceProvider did not hydrate all declared evidence: {missing}")

	@staticmethod
	def _validate_hypotheses(hypotheses: tuple[HypothesisNodeV1, ...], snapshot: ResearchRunSnapshot) -> None:
		if not isinstance(hypotheses, tuple):
			raise TypeError("HypothesisModel.propose must return tuple[HypothesisNodeV1, ...]")
		seen: set[str] = set()
		allowed_evidence = {str(item["evidence_id"]) for item in snapshot.evidence}
		allowed_papers = set(snapshot.paper_ids)
		for hypothesis in hypotheses:
			if not isinstance(hypothesis, HypothesisNodeV1):
				raise TypeError("HypothesisModel returned a non-HypothesisNodeV1 value")
			if hypothesis.hypothesis_id in seen:
				raise ValueError(f"duplicate hypothesis_id: {hypothesis.hypothesis_id}")
			if hypothesis.research_run_id != snapshot.research_run_id or hypothesis.graph_id != snapshot.context["graph_id"]:
				raise ValueError("hypothesis context does not match research run")
			if not set(hypothesis.source_paper_ids) <= allowed_papers:
				raise ValueError("hypothesis references paper outside graph")
			if not hypothesis.structural_only and not set(hypothesis.evidence_ids) <= allowed_evidence:
				raise ValueError("hypothesis references evidence outside retrieved bundle")
			seen.add(hypothesis.hypothesis_id)

	@staticmethod
	def _validate_experiments(
		experiments: tuple[ExperimentNodeV1, ...], snapshot: ResearchRunSnapshot,
		hypothesis_id: str,
	) -> None:
		if not isinstance(experiments, tuple):
			raise TypeError("ExperimentPlanner.plan must return tuple[ExperimentNodeV1, ...]")
		seen: set[str] = set()
		batch_ids = {item.experiment_id for item in experiments if isinstance(item, ExperimentNodeV1)}
		for experiment in experiments:
			if not isinstance(experiment, ExperimentNodeV1):
				raise TypeError("ExperimentPlanner returned a non-ExperimentNodeV1 value")
			if experiment.experiment_id in seen or experiment.experiment_id in snapshot.experiments:
				raise ValueError(f"duplicate experiment_id: {experiment.experiment_id}")
			if experiment.hypothesis_id != hypothesis_id:
				raise ValueError("experiment references the wrong hypothesis")
			if experiment.budget_id != snapshot.budget_spec.budget_id:
				raise ValueError("experiment references a different budget")
			if experiment.status != ExperimentStatus.CREATED:
				raise ValueError("planned experiments must start in created status")
			GraphResearchOrchestrator._reserved_compute_minutes(experiment)
			allowed_parents = set(snapshot.experiments) | batch_ids
			if not set(experiment.parent_experiment_ids) <= allowed_parents:
				raise ValueError("experiment references an unknown parent experiment")
			seen.add(experiment.experiment_id)

	@staticmethod
	def _validate_attempt(
		attempt: RunAttemptV1, experiment_id: str, attempt_number: int,
		snapshot: ResearchRunSnapshot,
	) -> None:
		if not isinstance(attempt, RunAttemptV1):
			raise TypeError("ExperimentExecutor.execute must return RunAttemptV1")
		if attempt.experiment_id != experiment_id or attempt.attempt_number != attempt_number:
			raise ValueError("run attempt does not match requested experiment and attempt number")
		if attempt.status not in {
			RunAttemptStatus.SUCCEEDED, RunAttemptStatus.FAILED_RETRYABLE,
			RunAttemptStatus.FAILED_FINAL, RunAttemptStatus.TIMED_OUT,
		}:
			raise ValueError("ExperimentExecutor must return a terminal RunAttemptV1")
		if any(item["run_attempt_id"] == attempt.run_attempt_id for item in snapshot.attempts):
			raise ValueError(f"duplicate run_attempt_id: {attempt.run_attempt_id}")
		if not attempt.started_at or not attempt.completed_at:
			raise ValueError("terminal run attempt must include start and completion timestamps")
		if attempt.status == RunAttemptStatus.SUCCEEDED:
			if attempt.exit_code != 0:
				raise ValueError("successful run attempt must have exit_code 0")
			if not attempt.result_artifacts:
				raise ValueError("successful run attempt must publish result artifacts")
		elif not attempt.failure_type:
			raise ValueError("failed run attempt must declare failure_type")

	@staticmethod
	def _validate_review_result(
		result: ExperimentReviewResult, experiment: ExperimentNodeV1,
		attempt: RunAttemptV1,
	) -> None:
		if not isinstance(result, ExperimentReviewResult):
			raise TypeError("ExperimentReviewer.review must return ExperimentReviewResult")
		review = result.review
		if review.experiment_id != experiment.experiment_id or review.run_attempt_id != attempt.run_attempt_id:
			raise ValueError("scientific review does not match experiment and successful attempt")
		if review.acceptance_rule != experiment.acceptance_rule:
			raise ValueError("scientific review changed the preregistered acceptance rule")
		if review.primary_metric_name != experiment.pre_registered_primary_metric:
			raise ValueError("scientific review changed the preregistered primary metric")
		seen_names: set[str] = set()
		seen_keys: set[str] = set()
		primary_value: float | None = None
		for metric in result.metrics:
			if metric.experiment_id != experiment.experiment_id:
				raise ValueError("review metric belongs to a different experiment")
			if metric.source_artifact_id not in attempt.result_artifacts:
				raise ValueError("review metric source is not a successful result artifact")
			if metric.metric_name in seen_names or metric.registry_key in seen_keys:
				raise ValueError("review metrics must have unique names and registry keys")
			seen_names.add(metric.metric_name)
			seen_keys.add(metric.registry_key)
			if metric.metric_name == review.primary_metric_name:
				primary_value = metric.value
		metric_payload = [metric.to_dict() for metric in sorted(result.metrics, key=lambda item: item.registry_key)]
		if review.metrics_content_hash != sha256_content_hash(metric_payload):
			raise ValueError("review metrics content hash mismatch")
		if review.primary_metric_value != primary_value:
			raise ValueError("review primary metric value does not match registered metrics")


__all__ = ["GraphResearchOrchestrator", "IntakeResult", "ResearchRunSnapshot"]
