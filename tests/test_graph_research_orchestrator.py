from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_alpha.graph_research.budget import BudgetSpec
from agent_alpha.graph_research.checkpoint import ResearchCheckpointStore
from agent_alpha.graph_research.models import DecisionRecord, ExperimentNodeV1, HypothesisNodeV1, RunAttemptV1
from agent_alpha.graph_research.orchestrator import GraphResearchOrchestrator
from agent_alpha.graph_research.ports import EvidenceRecord, MetricRecord
from agent_alpha.graph_research.review import build_rule_based_review
from agent_alpha.graph_research.states import (
	ExperimentStatus,
	GateStatus,
	HypothesisStatus,
	OperationType,
	ResearchRunStatus,
	RunAttemptStatus,
	ScientificVerdict,
	StructuredDecision,
)


class FixedClock:
	def now(self) -> datetime:
		return datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)


class FakeEvidenceProvider:
	def __init__(self) -> None:
		self.calls = 0

	def get_evidence(self, graph_id: str, graph_version: str, canonical_paper_ids: tuple[str, ...]) -> tuple[EvidenceRecord, ...]:
		self.calls += 1
		assert graph_id == "graph_1" and graph_version == "v1"
		assert canonical_paper_ids == ("paper_1", "paper_2")
		return (
			EvidenceRecord("evidence_1", "paper_1", "span_hash_1", "Bid depth predicts returns."),
			EvidenceRecord("evidence_2", "paper_2", "span_hash_2", "The effect weakens with wide spreads."),
		)


class FakeHypothesisModel:
	def __init__(self) -> None:
		self.calls = 0

	def propose(self, research_run_id: str, evidence: tuple[EvidenceRecord, ...]) -> tuple[HypothesisNodeV1, ...]:
		self.calls += 1
		assert len(evidence) == 2
		base = {
			"research_run_id": research_run_id, "graph_id": "graph_1",
			"mechanism": "inventory pressure", "market": "equities", "asset": "stocks",
			"frequency": "tick", "horizon": "one minute",
			"source_paper_ids": ["paper_1", "paper_2"], "source_claim_ids": [],
			"relation_evidence_ids": [], "novelty_rationale": "Cross-paper qualification.",
			"falsification_criteria": "Direction-adjusted RankIC is non-positive.",
			"expected_failure_modes": ["spread regime sensitivity"],
		}
		return (
			HypothesisNodeV1.create(
				**base, statement="Depth pressure predicts returns.", prediction="Positive next-minute return.",
				evidence_ids=["evidence_1"],
			),
			HypothesisNodeV1.create(
				**base, statement="Spread alone predicts returns.", prediction="Negative next-minute return.",
				evidence_ids=["evidence_2"],
			),
		)


class FakeApprovalPort:
	def __init__(self) -> None:
		self.calls = 0

	def review(self, hypothesis: HypothesisNodeV1) -> DecisionRecord:
		self.calls += 1
		if hypothesis.statement.startswith("Depth"):
			return DecisionRecord(StructuredDecision.PROCEED, "evidence_and_method_passed")
		return DecisionRecord(StructuredDecision.REJECT, "insufficient_incremental_mechanism")


class FakeExperimentPlanner:
	def __init__(self, *, primary_count: int = 1, reserved_compute_minutes: float = 2.0) -> None:
		self.calls = 0
		self.primary_count = primary_count
		self.reserved_compute_minutes = reserved_compute_minutes

	def plan(self, hypothesis: HypothesisNodeV1, budget_id: str) -> tuple[ExperimentNodeV1, ...]:
		self.calls += 1
		return tuple(
			ExperimentNodeV1.create(
				hypothesis_id=hypothesis.hypothesis_id,
				operation_type=OperationType.PRIMARY_TEST,
				factor_instance_ids=[f"factor_{index}"],
				pre_registered_primary_metric="direction_adjusted_rank_ic",
				acceptance_rule="direction_adjusted_rank_ic > 0.02",
				universe="csi500", market_data_version="market_snapshot_1",
				train_window="2020", validation_window="2021", test_window="2022",
				embargo=5, purge=5,
				cost_assumptions={"bps": 10, "reserved_compute_minutes": self.reserved_compute_minutes},
				robustness_dimensions=["spread_regime"], budget_id=budget_id,
				experiment_version=index + 1,
			)
			for index in range(self.primary_count)
		)


class FakeExperimentExecutor:
	def __init__(self, statuses: tuple[RunAttemptStatus, ...]) -> None:
		self.statuses = statuses
		self.calls = 0

	def execute(self, experiment: ExperimentNodeV1, attempt_number: int) -> RunAttemptV1:
		status = self.statuses[min(self.calls, len(self.statuses) - 1)]
		self.calls += 1
		succeeded = status == RunAttemptStatus.SUCCEEDED
		return RunAttemptV1.create(
			experiment_id=experiment.experiment_id, attempt_number=attempt_number,
			code_hash="code_hash", environment_hash="env_hash", scheduler="local_fake",
			resources={"cpu": 1}, timeout_seconds=600,
			result_artifacts=[f"result:{experiment.experiment_id}:{attempt_number}"] if succeeded else [],
			exit_code=0 if succeeded else 75,
			failure_type=None if succeeded else "transient_worker_loss",
			started_at="2026-08-10T10:00:00+00:00",
			completed_at="2026-08-10T10:01:00+00:00", status=status,
		)


class FakeExperimentReviewer:
	def __init__(self, metric_value: float | None = 0.03) -> None:
		self.metric_value = metric_value
		self.calls = 0

	def review(self, experiment: ExperimentNodeV1, attempt: RunAttemptV1):
		self.calls += 1
		metrics = () if self.metric_value is None else (
			MetricRecord(
				metric_name=experiment.pre_registered_primary_metric,
				experiment_id=experiment.experiment_id, value=self.metric_value,
				source_artifact_id=attempt.result_artifacts[0],
				content_hash=f"metric_hash:{experiment.experiment_id}",
			),
		)
		return build_rule_based_review(
			experiment=experiment, attempt=attempt, metrics=metrics,
			reviewer_revision="deterministic_reviewer_v1",
			reviewed_at="2026-08-10T10:02:00+00:00",
		)


class FakeMetricRegistry:
	def __init__(self, *, fail: bool = False) -> None:
		self.fail = fail
		self.calls = 0
		self.records: dict[str, MetricRecord] = {}

	def register(self, metric: MetricRecord) -> MetricRecord:
		self.calls += 1
		if self.fail:
			raise RuntimeError("registry unavailable")
		self.records.setdefault(metric.registry_key, metric)
		return self.records[metric.registry_key]


def _graph(*, evidence: bool = True) -> dict:
	graph = {
		"schema_version": "paper_graph_research_input_v0_test_only",
		"graph_id": "graph_1", "graph_version": "v1", "graph_artifact_id": "artifact_1",
		"content_hash": "graph_hash", "snapshot_id": "snapshot_1", "config_hash": "config_hash",
		"producer_revision": "paper_graph_rev_1", "seed_paper_ids": ["paper_1"],
		"paper_nodes": [
			{"canonical_paper_id": "paper_1", "identity_method": "exact_arxiv"},
			{"canonical_paper_id": "paper_2", "identity_method": "exact_doi"},
		],
		"relation_edges": [{
			"relation_type": "CITES", "source_paper_id": "paper_1", "target_paper_id": "paper_2",
			"directed": True, "provenance": {"source": "openalex_snapshot"},
		}],
		"research_question": "Does depth pressure survive liquidity-state qualification?",
	}
	if evidence:
		graph["evidence_spans"] = [
			{"evidence_id": "evidence_1", "canonical_paper_id": "paper_1", "content_hash": "span_hash_1"},
			{"evidence_id": "evidence_2", "canonical_paper_id": "paper_2", "content_hash": "span_hash_2"},
		]
	return graph


def _orchestrator(tmp_path: Path):
	evidence = FakeEvidenceProvider()
	model = FakeHypothesisModel()
	approval = FakeApprovalPort()
	orchestrator = GraphResearchOrchestrator(
		checkpoint_store=ResearchCheckpointStore(tmp_path), evidence_provider=evidence,
		hypothesis_model=model, approval_port=approval, clock=FixedClock(),
	)
	return orchestrator, evidence, model, approval


def _execution_orchestrator(
	tmp_path: Path, *, planner: FakeExperimentPlanner | None = None,
	executor: FakeExperimentExecutor | None = None,
	reviewer: FakeExperimentReviewer | None = None,
	registry: FakeMetricRegistry | None = None,
):
	evidence = FakeEvidenceProvider()
	model = FakeHypothesisModel()
	approval = FakeApprovalPort()
	planner = planner or FakeExperimentPlanner()
	executor = executor or FakeExperimentExecutor((RunAttemptStatus.SUCCEEDED,))
	reviewer = reviewer or FakeExperimentReviewer()
	registry = registry or FakeMetricRegistry()
	orchestrator = GraphResearchOrchestrator(
		checkpoint_store=ResearchCheckpointStore(tmp_path), evidence_provider=evidence,
		hypothesis_model=model, approval_port=approval, experiment_planner=planner,
		experiment_executor=executor, experiment_reviewer=reviewer,
		metric_registry=registry, clock=FixedClock(),
	)
	return orchestrator, planner, executor


def _approved_run(orchestrator: GraphResearchOrchestrator, budget: BudgetSpec) -> str:
	intake = orchestrator.start(_graph(), budget_spec=budget)
	assert intake.snapshot
	snapshot = orchestrator.prepare_hypotheses(intake.snapshot.research_run_id)
	assert snapshot.run_status == ResearchRunStatus.APPROVAL_PENDING
	return snapshot.research_run_id


def _reviewable_run(orchestrator: GraphResearchOrchestrator, budget: BudgetSpec) -> str:
	run_id = _approved_run(orchestrator, budget)
	orchestrator.plan_experiments(run_id)
	snapshot = orchestrator.execute_experiments(run_id)
	assert snapshot.run_status == ResearchRunStatus.REVIEW_PENDING
	return run_id


def test_orchestrator_runs_intake_evidence_hypothesis_and_approval_idempotently(tmp_path: Path) -> None:
	orchestrator, evidence, model, approval = _orchestrator(tmp_path)
	budget = BudgetSpec(max_hypotheses_per_graph=3, max_llm_calls=1, max_llm_tokens=0)

	intake = orchestrator.start(_graph(), budget_spec=budget)
	assert intake.gate_decision.status == GateStatus.ELIGIBLE
	assert intake.snapshot and intake.snapshot.run_status == ResearchRunStatus.EVIDENCE_READY
	snapshot = orchestrator.prepare_hypotheses(intake.snapshot.research_run_id)

	assert snapshot.run_status == ResearchRunStatus.APPROVAL_PENDING
	assert sorted(status.value for status in snapshot.hypothesis_statuses.values()) == ["abandoned", "approved"]
	assert snapshot.budget_usage.llm_calls == 1
	assert snapshot.budget_usage.hypotheses == 2
	assert evidence.calls == model.calls == 1
	assert approval.calls == 2
	assert set(snapshot.expected_evidence) == {"evidence_1", "evidence_2"}

	resumed = orchestrator.prepare_hypotheses(snapshot.research_run_id)
	assert resumed.event_count == snapshot.event_count
	assert evidence.calls == model.calls == 1
	assert approval.calls == 2


def test_orchestrator_start_replays_with_a_later_clock_time(tmp_path: Path) -> None:
	orchestrator, _, _, _ = _orchestrator(tmp_path)
	budget = BudgetSpec(max_llm_calls=1)
	first = orchestrator.start(_graph(), budget_spec=budget)
	assert first.snapshot

	class LaterClock:
		def now(self) -> datetime:
			return datetime(2026, 8, 10, 11, 0, tzinfo=timezone.utc)

	orchestrator.clock = LaterClock()
	second = orchestrator.start(_graph(), budget_spec=budget)
	assert second.snapshot and second.snapshot.event_count == first.snapshot.event_count


def test_orchestrator_pauses_before_ports_when_digest_is_required(tmp_path: Path) -> None:
	orchestrator, evidence, model, approval = _orchestrator(tmp_path)
	intake = orchestrator.start(_graph(evidence=False), budget_spec=BudgetSpec(max_llm_calls=1))

	assert intake.gate_decision.status == GateStatus.NEEDS_DIGEST
	assert intake.snapshot and intake.snapshot.run_status == ResearchRunStatus.PAUSED_EVIDENCE
	assert orchestrator.prepare_hypotheses(intake.snapshot.research_run_id).run_status == ResearchRunStatus.PAUSED_EVIDENCE
	assert evidence.calls == model.calls == approval.calls == 0


def test_orchestrator_pauses_on_llm_budget_without_calling_model(tmp_path: Path) -> None:
	orchestrator, evidence, model, approval = _orchestrator(tmp_path)
	intake = orchestrator.start(_graph(), budget_spec=BudgetSpec(max_llm_calls=0))
	assert intake.snapshot

	snapshot = orchestrator.prepare_hypotheses(intake.snapshot.research_run_id)

	assert snapshot.run_status == ResearchRunStatus.PAUSED_BUDGET
	assert evidence.calls == 1
	assert model.calls == approval.calls == 0
	assert snapshot.budget_usage.llm_calls == 0


def test_orchestrator_preregisters_retries_and_stops_for_review_idempotently(tmp_path: Path) -> None:
	executor = FakeExperimentExecutor((RunAttemptStatus.FAILED_RETRYABLE, RunAttemptStatus.SUCCEEDED))
	orchestrator, planner, executor = _execution_orchestrator(tmp_path, executor=executor)
	budget = BudgetSpec(max_llm_calls=2, max_attempts_per_experiment=3, max_total_attempts=3)
	run_id = _approved_run(orchestrator, budget)

	planned = orchestrator.plan_experiments(run_id)
	assert planned.run_status == ResearchRunStatus.EXPERIMENTS_QUEUED
	assert set(planned.experiment_statuses.values()) == {ExperimentStatus.QUEUED}
	assert [status for status in planned.hypothesis_statuses.values()].count(HypothesisStatus.TESTING) == 1
	assert planned.budget_usage.llm_calls == 2
	assert planned.budget_usage.primary_candidates == 1
	assert planner.calls == 1

	replayed_plan = orchestrator.plan_experiments(run_id)
	assert replayed_plan.event_count == planned.event_count
	assert planner.calls == 1

	completed = orchestrator.execute_experiments(run_id)
	assert completed.run_status == ResearchRunStatus.REVIEW_PENDING
	assert set(completed.experiment_statuses.values()) == {ExperimentStatus.REVIEW_PENDING}
	assert [item["status"] for item in completed.attempts] == [
		RunAttemptStatus.FAILED_RETRYABLE.value, RunAttemptStatus.SUCCEEDED.value,
	]
	assert completed.budget_usage.attempts == 2
	assert completed.budget_usage.compute_minutes == 4.0
	assert executor.calls == 2

	replayed_execution = orchestrator.execute_experiments(run_id)
	assert replayed_execution.event_count == completed.event_count
	assert executor.calls == 2


def test_orchestrator_attempt_limit_turns_retryable_failure_final(tmp_path: Path) -> None:
	executor = FakeExperimentExecutor((RunAttemptStatus.FAILED_RETRYABLE,))
	orchestrator, _, executor = _execution_orchestrator(tmp_path, executor=executor)
	budget = BudgetSpec(max_llm_calls=2, max_attempts_per_experiment=1, max_total_attempts=5)
	run_id = _approved_run(orchestrator, budget)
	orchestrator.plan_experiments(run_id)

	snapshot = orchestrator.execute_experiments(run_id)

	assert snapshot.run_status == ResearchRunStatus.FAILED_FINAL
	assert set(snapshot.experiment_statuses.values()) == {ExperimentStatus.FAILED_FINAL}
	assert len(snapshot.attempts) == executor.calls == 1


def test_orchestrator_reserves_compute_budget_before_executor_call(tmp_path: Path) -> None:
	planner = FakeExperimentPlanner(reserved_compute_minutes=5.0)
	executor = FakeExperimentExecutor((RunAttemptStatus.SUCCEEDED,))
	orchestrator, _, executor = _execution_orchestrator(tmp_path, planner=planner, executor=executor)
	budget = BudgetSpec(max_llm_calls=2, max_compute_minutes=4.0)
	run_id = _approved_run(orchestrator, budget)
	orchestrator.plan_experiments(run_id)

	snapshot = orchestrator.execute_experiments(run_id)

	assert snapshot.run_status == ResearchRunStatus.PAUSED_BUDGET
	assert snapshot.budget_usage.attempts == 0
	assert snapshot.budget_usage.compute_minutes == 0
	assert executor.calls == 0


def test_orchestrator_closes_invalid_executor_success_as_contract_failure(tmp_path: Path) -> None:
	class InvalidExecutor(FakeExperimentExecutor):
		def execute(self, experiment: ExperimentNodeV1, attempt_number: int) -> RunAttemptV1:
			self.calls += 1
			return RunAttemptV1.create(
				experiment_id=experiment.experiment_id, attempt_number=attempt_number,
				code_hash="code_hash", environment_hash="env_hash", scheduler="local_fake",
				timeout_seconds=60, exit_code=0, result_artifacts=[],
				status=RunAttemptStatus.SUCCEEDED,
			)

	executor = InvalidExecutor((RunAttemptStatus.SUCCEEDED,))
	orchestrator, _, executor = _execution_orchestrator(tmp_path, executor=executor)
	budget = BudgetSpec(max_llm_calls=2)
	run_id = _approved_run(orchestrator, budget)
	orchestrator.plan_experiments(run_id)

	snapshot = orchestrator.execute_experiments(run_id)

	assert snapshot.run_status == ResearchRunStatus.FAILED_FINAL
	assert set(snapshot.experiment_statuses.values()) == {ExperimentStatus.FAILED_FINAL}
	assert not snapshot.attempts
	assert snapshot.execution_errors[0]["error_type"] == "ValueError"
	assert executor.calls == 1


def test_orchestrator_pauses_when_planner_exceeds_primary_candidate_budget(tmp_path: Path) -> None:
	planner = FakeExperimentPlanner(primary_count=2)
	orchestrator, planner, executor = _execution_orchestrator(tmp_path, planner=planner)
	budget = BudgetSpec(
		max_llm_calls=2, max_primary_candidates_per_hypothesis=1,
	)
	run_id = _approved_run(orchestrator, budget)

	snapshot = orchestrator.plan_experiments(run_id)

	assert snapshot.run_status == ResearchRunStatus.PAUSED_BUDGET
	assert not snapshot.experiments
	assert snapshot.budget_usage.primary_candidates == 0
	assert planner.calls == 1
	assert executor.calls == 0
	assert orchestrator.plan_experiments(run_id).event_count == snapshot.event_count
	assert planner.calls == 1


def test_orchestrator_commits_supported_review_and_metrics_idempotently(tmp_path: Path) -> None:
	reviewer = FakeExperimentReviewer(metric_value=0.03)
	registry = FakeMetricRegistry()
	orchestrator, _, _ = _execution_orchestrator(tmp_path, reviewer=reviewer, registry=registry)
	run_id = _reviewable_run(orchestrator, BudgetSpec(max_llm_calls=3))

	snapshot = orchestrator.review_experiments(run_id)

	assert snapshot.run_status == ResearchRunStatus.COMPLETED
	assert set(snapshot.experiment_statuses.values()) == {ExperimentStatus.COMPLETED}
	assert [status for status in snapshot.hypothesis_statuses.values()].count(HypothesisStatus.SUPPORTED) == 1
	assert {review["verdict"] for review in snapshot.experiment_reviews.values()} == {ScientificVerdict.SUPPORTED.value}
	assert len(snapshot.registered_metric_keys) == 1
	assert snapshot.budget_usage.llm_calls == 3
	assert reviewer.calls == registry.calls == 1

	replayed = orchestrator.review_experiments(run_id)
	assert replayed.event_count == snapshot.event_count
	assert reviewer.calls == registry.calls == 1


def test_orchestrator_maps_failed_acceptance_rule_to_refuted(tmp_path: Path) -> None:
	reviewer = FakeExperimentReviewer(metric_value=0.01)
	orchestrator, _, _ = _execution_orchestrator(tmp_path, reviewer=reviewer)
	run_id = _reviewable_run(orchestrator, BudgetSpec(max_llm_calls=3))

	snapshot = orchestrator.review_experiments(run_id)

	assert snapshot.run_status == ResearchRunStatus.COMPLETED
	assert [status for status in snapshot.hypothesis_statuses.values()].count(HypothesisStatus.REFUTED) == 1
	assert {review["verdict"] for review in snapshot.experiment_reviews.values()} == {ScientificVerdict.REFUTED.value}


def test_orchestrator_never_maps_technical_failure_to_refuted(tmp_path: Path) -> None:
	planner = FakeExperimentPlanner(primary_count=2)
	executor = FakeExperimentExecutor((RunAttemptStatus.FAILED_FINAL, RunAttemptStatus.SUCCEEDED))
	reviewer = FakeExperimentReviewer(metric_value=0.03)
	orchestrator, _, _ = _execution_orchestrator(
		tmp_path, planner=planner, executor=executor, reviewer=reviewer,
	)
	budget = BudgetSpec(max_llm_calls=3, max_primary_candidates_per_hypothesis=2)
	run_id = _reviewable_run(orchestrator, budget)

	snapshot = orchestrator.review_experiments(run_id)

	assert snapshot.run_status == ResearchRunStatus.COMPLETED
	assert [status for status in snapshot.hypothesis_statuses.values()].count(HypothesisStatus.INCONCLUSIVE) == 1
	assert list(snapshot.experiment_statuses.values()).count(ExperimentStatus.FAILED_FINAL) == 1
	assert reviewer.calls == 1


def test_orchestrator_pauses_review_before_reviewer_when_llm_budget_is_exhausted(tmp_path: Path) -> None:
	reviewer = FakeExperimentReviewer()
	registry = FakeMetricRegistry()
	orchestrator, _, _ = _execution_orchestrator(tmp_path, reviewer=reviewer, registry=registry)
	run_id = _reviewable_run(orchestrator, BudgetSpec(max_llm_calls=2))

	snapshot = orchestrator.review_experiments(run_id)

	assert snapshot.run_status == ResearchRunStatus.PAUSED_BUDGET
	assert reviewer.calls == registry.calls == 0
	assert not snapshot.experiment_reviews


def test_orchestrator_resumes_metric_outbox_without_repeating_reviewer(tmp_path: Path) -> None:
	reviewer = FakeExperimentReviewer()
	registry = FakeMetricRegistry(fail=True)
	orchestrator, _, _ = _execution_orchestrator(tmp_path, reviewer=reviewer, registry=registry)
	run_id = _reviewable_run(orchestrator, BudgetSpec(max_llm_calls=3))

	with pytest.raises(RuntimeError, match="registry unavailable"):
		orchestrator.review_experiments(run_id)
	interrupted = orchestrator.snapshot(run_id)
	assert interrupted.run_status == ResearchRunStatus.REVIEW_PENDING
	assert len(interrupted.experiment_reviews) == 1
	assert reviewer.calls == registry.calls == 1

	registry.fail = False
	resumed = orchestrator.review_experiments(run_id)

	assert resumed.run_status == ResearchRunStatus.COMPLETED
	assert reviewer.calls == 1
	assert registry.calls == 2
