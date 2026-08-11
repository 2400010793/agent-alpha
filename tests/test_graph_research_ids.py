from __future__ import annotations

import math

import pytest

from agent_alpha.graph_research.ids import (
	canonical_json,
	experiment_id,
	hypothesis_id,
	research_run_id,
	run_attempt_id,
)


def _run_id(**overrides: str) -> str:
	values = {
		"graph_id": "graph_1", "graph_version": "v1", "graph_artifact_id": "artifact_1",
		"graph_content_hash": "graph_hash", "evidence_content_hash": "evidence_hash",
		"research_config_hash": "config_hash", "snapshot_id": "snapshot_1",
	}
	values.update(overrides)
	return research_run_id(**values)


def test_canonical_json_normalizes_mapping_and_sets_but_preserves_list_order() -> None:
	assert canonical_json({"b": 2, "a": {"y", "x"}}) == canonical_json({"a": {"x", "y"}, "b": 2})
	assert canonical_json({"path": ["a", "b"]}) != canonical_json({"path": ["b", "a"]})


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_canonical_json_rejects_non_finite_numbers(value: float) -> None:
	with pytest.raises(ValueError):
		canonical_json({"bad": value})


@pytest.mark.parametrize(
	"changed",
	[
		{"graph_version": "v2"}, {"graph_content_hash": "different_graph"},
		{"evidence_content_hash": "different_evidence"}, {"research_config_hash": "different_config"},
	],
)
def test_research_run_identity_changes_with_immutable_inputs(changed: dict[str, str]) -> None:
	assert _run_id() != _run_id(**changed)


def test_created_at_is_not_a_research_run_identity_input() -> None:
	# The function deliberately has no created_at parameter; context creation is tested separately.
	assert _run_id() == _run_id()


def test_hypothesis_identity_normalizes_identity_list_order() -> None:
	base = dict(
		research_run_id=_run_id(), graph_id="graph_1", statement="S", mechanism="M", prediction="P",
		source_paper_ids=["paper_b", "paper_a"], evidence_ids=["evidence_b", "evidence_a"],
	)
	other = dict(base, source_paper_ids=["paper_a", "paper_b"], evidence_ids=["evidence_a", "evidence_b"])
	assert hypothesis_id(**base) == hypothesis_id(**other)


def test_preregistration_and_attempt_identity_are_isolated() -> None:
	exp_a = experiment_id(hypothesis_id="hyp_a", experiment_version=1, preregistration={"metric": "ic"})
	exp_b = experiment_id(hypothesis_id="hyp_a", experiment_version=1, preregistration={"metric": "sharpe"})
	assert exp_a != exp_b
	assert run_attempt_id(experiment_id=exp_a, attempt_number=1, code_hash="c", environment_hash="e") != run_attempt_id(
		experiment_id=exp_a, attempt_number=2, code_hash="c", environment_hash="e"
	)
	other_graph_experiment = experiment_id(hypothesis_id="hyp_other_graph", experiment_version=1, preregistration={"metric": "ic"})
	assert run_attempt_id(experiment_id=exp_a, attempt_number=1, code_hash="c", environment_hash="e") != run_attempt_id(
		experiment_id=other_graph_experiment, attempt_number=1, code_hash="c", environment_hash="e"
	)
