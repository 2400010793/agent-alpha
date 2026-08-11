from __future__ import annotations

import pytest

from agent_alpha.graph_research.state_machine import (
	CANDIDATE_TRANSITIONS,
	HYPOTHESIS_TRANSITIONS,
	RUN_TRANSITIONS,
	CandidateStateMachine,
	HypothesisStateMachine,
	InvalidStateTransition,
	ResearchRunStateMachine,
	structured_decision,
)
from agent_alpha.graph_research.states import CandidateStatus, ResearchRunStatus, StructuredDecision


@pytest.mark.parametrize("source,targets", list(RUN_TRANSITIONS.items()))
def test_every_declared_run_transition_is_accepted(source: ResearchRunStatus, targets: frozenset[ResearchRunStatus]) -> None:
	for target in targets:
		assert ResearchRunStateMachine(source).transition(target) == target


@pytest.mark.parametrize("source,targets", list(HYPOTHESIS_TRANSITIONS.items()))
def test_every_declared_hypothesis_transition_is_accepted(source, targets) -> None:
	for target in targets:
		assert HypothesisStateMachine(source).transition(target) == target


def test_illegal_transition_preserves_original_state_and_protects_terminals() -> None:
	machine = ResearchRunStateMachine()
	with pytest.raises(InvalidStateTransition):
		machine.transition(ResearchRunStatus.COMPLETED)
	assert machine.state == ResearchRunStatus.CREATED
	for terminal in (ResearchRunStatus.COMPLETED, ResearchRunStatus.FAILED_FINAL):
		terminal_machine = ResearchRunStateMachine(terminal)
		with pytest.raises(InvalidStateTransition):
			terminal_machine.transition(ResearchRunStatus.RUNNING)
		assert terminal_machine.state == terminal


def test_retry_and_budget_pause_resume_are_scientifically_distinct() -> None:
	assert ResearchRunStateMachine(ResearchRunStatus.FAILED_RETRYABLE).transition(ResearchRunStatus.EXPERIMENTS_QUEUED)
	assert ResearchRunStateMachine(ResearchRunStatus.PAUSED_BUDGET).transition(ResearchRunStatus.EXPERIMENTS_QUEUED)
	with pytest.raises(InvalidStateTransition):
		ResearchRunStateMachine(ResearchRunStatus.PAUSED_BUDGET).transition(ResearchRunStatus.COMPLETED)
	assert ResearchRunStateMachine(ResearchRunStatus.PAUSED_BUDGET).transition(ResearchRunStatus.EVIDENCE_READY)


def test_candidate_transitions_and_terminal_protection() -> None:
	machine = CandidateStateMachine()
	for target in (
		CandidateStatus.VALIDATED, CandidateStatus.RENDERED, CandidateStatus.COMPILED,
		CandidateStatus.SCHEDULED, CandidateStatus.RUNNING, CandidateStatus.EVALUATED, CandidateStatus.ACCEPTED,
	):
		machine.transition(target)
	with pytest.raises(InvalidStateTransition):
		machine.transition(CandidateStatus.RUNNING)
	assert machine.state == CandidateStatus.ACCEPTED


def test_structured_decision_enforces_budget_and_retry_rules() -> None:
	record = structured_decision(StructuredDecision.REFINE, "weak_primary_metric")
	assert record.to_dict() == {"decision": "refine", "reason_code": "weak_primary_metric"}
	with pytest.raises(ValueError, match="budget exhaustion"):
		structured_decision(StructuredDecision.PROCEED, "continue", budget_exhausted=True)
	with pytest.raises(ValueError, match="scientific pivot"):
		structured_decision(StructuredDecision.PIVOT, "scheduler_error", infrastructure_retry=True)
