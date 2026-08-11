from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent_alpha.graph_research.ids import experiment_id, research_run_id
from agent_alpha.graph_research.models import ExperimentNodeV1, GraphResearchContext, HypothesisNodeV1, RunAttemptV1
from agent_alpha.graph_research.states import HypothesisStatus, OperationType


NOW = "2026-08-10T10:00:00+00:00"


def _context(created_at: str = NOW, **overrides: str) -> GraphResearchContext:
	values = {
		"graph_id": "graph_1", "graph_version": "v1", "graph_artifact_id": "artifact_1",
		"graph_content_hash": "graph_hash", "evidence_bundle_id": "bundle_1",
		"evidence_content_hash": "evidence_hash", "research_config_hash": "config_hash",
		"snapshot_id": "snapshot_1", "producer_revision": "rev_1", "created_at": created_at,
	}
	values.update(overrides)
	return GraphResearchContext.create(**values)


def _hypothesis(**overrides: object) -> HypothesisNodeV1:
	values: dict[str, object] = {
		"research_run_id": _context().research_run_id, "graph_id": "graph_1", "statement": "Depth predicts returns.",
		"mechanism": "Inventory pressure", "prediction": "Next-minute returns rise with bid imbalance.",
		"market": "equities", "asset": "stocks", "frequency": "tick", "horizon": "one minute",
		"source_paper_ids": ["paper_b", "paper_a"], "source_claim_ids": ["claim_1"],
		"evidence_ids": ["evidence_1"], "relation_evidence_ids": ["relation_1"],
		"novelty_rationale": "Tests the linked mechanism.", "falsification_criteria": "IC is non-positive.",
		"expected_failure_modes": ["cost sensitivity"],
	}
	values.update(overrides)
	return HypothesisNodeV1.create(**values)


def test_context_is_frozen_stable_and_created_at_is_not_identity() -> None:
	first = _context("2026-08-10T10:00:00+00:00")
	second = _context("2026-08-10T11:00:00Z")
	assert first.research_run_id == second.research_run_id
	assert first.to_dict() == first.to_dict()
	with pytest.raises(FrozenInstanceError):
		first.graph_id = "other"  # type: ignore[misc]


@pytest.mark.parametrize("timestamp", ["2026-08-10T10:00:00", "not-a-time", "2026-08-10T10:00:00+08:00"])
def test_context_requires_utc_iso_time(timestamp: str) -> None:
	with pytest.raises(ValueError):
		_context(timestamp)


def test_hypothesis_requires_evidence_unless_explicitly_structural_only() -> None:
	with pytest.raises(ValueError, match="factual hypotheses"):
		_hypothesis(evidence_ids=[])
	structural = _hypothesis(evidence_ids=[], structural_only=True)
	assert structural.structural_only is True
	assert structural.evidence_ids == ()


def test_hypothesis_normalizes_ids_and_rejects_unknown_status() -> None:
	hypothesis = _hypothesis()
	assert hypothesis.source_paper_ids == ("paper_a", "paper_b")
	assert hypothesis.to_dict()["status"] == "proposed"
	with pytest.raises(ValueError, match="unknown hypothesis status"):
		_hypothesis(status="invented")
	with pytest.raises(ValueError):
		_hypothesis(source_paper_ids=[""])


def test_experiment_identity_covers_preregistration_and_deep_freezes_mappings() -> None:
	values = {
		"hypothesis_id": _hypothesis().hypothesis_id, "operation_type": OperationType.PRIMARY_TEST,
		"factor_instance_ids": ["factor_2", "factor_1"], "pre_registered_primary_metric": "IC",
		"acceptance_rule": "mean_ic > 0.02", "universe": "CSI300", "market_data_version": "md_v1",
		"train_window": "2020-2022", "validation_window": "2023", "test_window": "2024",
		"embargo": 1, "purge": 1, "cost_assumptions": {"bps": 5, "nested": {"slippage": 2}},
		"robustness_dimensions": ["cost", "regime"], "budget_id": "budget_1",
	}
	first = ExperimentNodeV1.create(**values)
	second = ExperimentNodeV1.create(**dict(values, acceptance_rule="mean_ic > 0.03"))
	assert first.experiment_id != second.experiment_id
	with pytest.raises(TypeError):
		first.cost_assumptions["bps"] = 10  # type: ignore[index]
	assert first.to_dict()["factor_instance_ids"] == ["factor_1", "factor_2"]


def test_run_attempt_retry_identity_and_time_validation() -> None:
	attempt = RunAttemptV1.create(
		experiment_id="exp_1", attempt_number=1, code_hash="code", environment_hash="env",
		scheduler="none", resources={"cpu": 1}, timeout_seconds=60,
	)
	retry = RunAttemptV1.create(
		experiment_id="exp_1", attempt_number=2, code_hash="code", environment_hash="env",
		scheduler="none", resources={"cpu": 1}, timeout_seconds=60,
	)
	assert attempt.run_attempt_id != retry.run_attempt_id
	with pytest.raises(ValueError, match="cannot precede"):
		RunAttemptV1.create(
			experiment_id="exp_1", attempt_number=1, code_hash="code", environment_hash="env",
			scheduler="none", resources={}, timeout_seconds=60,
			started_at="2026-08-10T11:00:00Z", completed_at="2026-08-10T10:00:00Z",
		)
