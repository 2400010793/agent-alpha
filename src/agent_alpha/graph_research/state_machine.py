from __future__ import annotations

from collections.abc import Mapping, Set
from typing import Generic, Type, TypeVar

from .models import DecisionRecord
from .states import (
	CandidateStatus,
	ExperimentStatus,
	HypothesisStatus,
	ResearchRunStatus,
	StringEnum,
	StructuredDecision,
)


StateT = TypeVar("StateT", bound=StringEnum)


class InvalidStateTransition(ValueError):
	pass


RUN_TRANSITIONS = {
	ResearchRunStatus.CREATED: frozenset({ResearchRunStatus.VALIDATED}),
	ResearchRunStatus.VALIDATED: frozenset({ResearchRunStatus.EVIDENCE_READY, ResearchRunStatus.PAUSED_EVIDENCE}),
	ResearchRunStatus.EVIDENCE_READY: frozenset({
		ResearchRunStatus.HYPOTHESES_READY, ResearchRunStatus.PAUSED_BUDGET,
		ResearchRunStatus.PAUSED_EVIDENCE, ResearchRunStatus.FAILED_RETRYABLE,
		ResearchRunStatus.FAILED_FINAL,
	}),
	ResearchRunStatus.HYPOTHESES_READY: frozenset({
		ResearchRunStatus.APPROVAL_PENDING, ResearchRunStatus.PAUSED_BUDGET,
		ResearchRunStatus.PAUSED_EVIDENCE, ResearchRunStatus.FAILED_FINAL,
	}),
	ResearchRunStatus.APPROVAL_PENDING: frozenset({
		ResearchRunStatus.EXPERIMENTS_QUEUED, ResearchRunStatus.PAUSED_EVIDENCE,
		ResearchRunStatus.PAUSED_BUDGET, ResearchRunStatus.FAILED_FINAL,
	}),
	ResearchRunStatus.EXPERIMENTS_QUEUED: frozenset({
		ResearchRunStatus.RUNNING, ResearchRunStatus.PAUSED_BUDGET,
		ResearchRunStatus.FAILED_FINAL,
	}),
	ResearchRunStatus.RUNNING: frozenset({
		ResearchRunStatus.REVIEW_PENDING, ResearchRunStatus.PAUSED_BUDGET,
		ResearchRunStatus.FAILED_RETRYABLE, ResearchRunStatus.FAILED_FINAL,
	}),
	ResearchRunStatus.REVIEW_PENDING: frozenset({
		ResearchRunStatus.COMPLETED, ResearchRunStatus.EXPERIMENTS_QUEUED,
		ResearchRunStatus.PAUSED_BUDGET,
	}),
	ResearchRunStatus.PAUSED_EVIDENCE: frozenset({ResearchRunStatus.VALIDATED}),
	ResearchRunStatus.PAUSED_BUDGET: frozenset({
		ResearchRunStatus.VALIDATED, ResearchRunStatus.EVIDENCE_READY,
		ResearchRunStatus.HYPOTHESES_READY, ResearchRunStatus.APPROVAL_PENDING,
		ResearchRunStatus.EXPERIMENTS_QUEUED, ResearchRunStatus.RUNNING,
		ResearchRunStatus.REVIEW_PENDING,
	}),
	ResearchRunStatus.FAILED_RETRYABLE: frozenset({ResearchRunStatus.EXPERIMENTS_QUEUED}),
	ResearchRunStatus.COMPLETED: frozenset(),
	ResearchRunStatus.FAILED_FINAL: frozenset(),
}

HYPOTHESIS_TRANSITIONS = {
	HypothesisStatus.PROPOSED: frozenset({HypothesisStatus.EVIDENCE_CHECKED, HypothesisStatus.ABANDONED}),
	HypothesisStatus.EVIDENCE_CHECKED: frozenset({HypothesisStatus.APPROVED, HypothesisStatus.ABANDONED}),
	HypothesisStatus.APPROVED: frozenset({HypothesisStatus.TESTING}),
	HypothesisStatus.TESTING: frozenset({
		HypothesisStatus.SUPPORTED, HypothesisStatus.REFUTED,
		HypothesisStatus.INCONCLUSIVE, HypothesisStatus.ABANDONED,
	}),
	HypothesisStatus.SUPPORTED: frozenset(),
	HypothesisStatus.REFUTED: frozenset(),
	HypothesisStatus.INCONCLUSIVE: frozenset(),
	HypothesisStatus.ABANDONED: frozenset(),
}

EXPERIMENT_TRANSITIONS = {
	ExperimentStatus.CREATED: frozenset({ExperimentStatus.PREREGISTERED}),
	ExperimentStatus.PREREGISTERED: frozenset({ExperimentStatus.QUEUED}),
	ExperimentStatus.QUEUED: frozenset({ExperimentStatus.RUNNING}),
	ExperimentStatus.RUNNING: frozenset({
		ExperimentStatus.REVIEW_PENDING, ExperimentStatus.FAILED_RETRYABLE, ExperimentStatus.FAILED_FINAL,
	}),
	ExperimentStatus.FAILED_RETRYABLE: frozenset({ExperimentStatus.QUEUED, ExperimentStatus.FAILED_FINAL}),
	ExperimentStatus.REVIEW_PENDING: frozenset({ExperimentStatus.COMPLETED, ExperimentStatus.QUEUED}),
	ExperimentStatus.COMPLETED: frozenset(),
	ExperimentStatus.FAILED_FINAL: frozenset(),
}

CANDIDATE_TRANSITIONS = {
	CandidateStatus.PROPOSED: frozenset({CandidateStatus.VALIDATED, CandidateStatus.REJECTED}),
	CandidateStatus.VALIDATED: frozenset({CandidateStatus.RENDERED, CandidateStatus.REJECTED}),
	CandidateStatus.RENDERED: frozenset({CandidateStatus.COMPILED, CandidateStatus.FAILED}),
	CandidateStatus.COMPILED: frozenset({CandidateStatus.SCHEDULED, CandidateStatus.FAILED}),
	CandidateStatus.SCHEDULED: frozenset({CandidateStatus.RUNNING, CandidateStatus.FAILED, CandidateStatus.TIMED_OUT}),
	CandidateStatus.RUNNING: frozenset({CandidateStatus.EVALUATED, CandidateStatus.FAILED, CandidateStatus.TIMED_OUT}),
	CandidateStatus.EVALUATED: frozenset({
		CandidateStatus.ACCEPTED, CandidateStatus.REVISE, CandidateStatus.REJECTED, CandidateStatus.SUPERSEDED,
	}),
	CandidateStatus.REVISE: frozenset({CandidateStatus.VALIDATED, CandidateStatus.REJECTED, CandidateStatus.SUPERSEDED}),
	CandidateStatus.ACCEPTED: frozenset(),
	CandidateStatus.REJECTED: frozenset(),
	CandidateStatus.FAILED: frozenset(),
	CandidateStatus.TIMED_OUT: frozenset(),
	CandidateStatus.SUPERSEDED: frozenset(),
}


def validate_transition(
	current: StateT,
	target: StateT,
	transitions: Mapping[StateT, Set[StateT]],
) -> StateT:
	if target not in transitions.get(current, frozenset()):
		raise InvalidStateTransition("illegal transition: %s -> %s" % (current.value, target.value))
	return target


class StateMachine(Generic[StateT]):
	def __init__(
		self,
		initial_state: StateT,
		state_type: Type[StateT],
		transitions: Mapping[StateT, Set[StateT]],
	) -> None:
		try:
			self._state = initial_state if isinstance(initial_state, state_type) else state_type(initial_state)
		except (TypeError, ValueError):
			raise ValueError("unknown %s state: %r" % (state_type.__name__, initial_state)) from None
		self._state_type = state_type
		self._transitions = transitions

	@property
	def state(self) -> StateT:
		return self._state

	@property
	def allowed_targets(self) -> frozenset[StateT]:
		return frozenset(self._transitions.get(self._state, frozenset()))

	def transition(self, target: StateT) -> StateT:
		try:
			normalized = target if isinstance(target, self._state_type) else self._state_type(target)
		except (TypeError, ValueError):
			raise ValueError("unknown %s state: %r" % (self._state_type.__name__, target)) from None
		# Assignment happens only after validation, preserving state on failure.
		validated = validate_transition(self._state, normalized, self._transitions)
		self._state = validated
		return self._state


class ResearchRunStateMachine(StateMachine[ResearchRunStatus]):
	def __init__(self, initial_state: ResearchRunStatus = ResearchRunStatus.CREATED) -> None:
		super().__init__(initial_state, ResearchRunStatus, RUN_TRANSITIONS)


class HypothesisStateMachine(StateMachine[HypothesisStatus]):
	def __init__(self, initial_state: HypothesisStatus = HypothesisStatus.PROPOSED) -> None:
		super().__init__(initial_state, HypothesisStatus, HYPOTHESIS_TRANSITIONS)


class ExperimentStateMachine(StateMachine[ExperimentStatus]):
	def __init__(self, initial_state: ExperimentStatus = ExperimentStatus.CREATED) -> None:
		super().__init__(initial_state, ExperimentStatus, EXPERIMENT_TRANSITIONS)


class CandidateStateMachine(StateMachine[CandidateStatus]):
	def __init__(self, initial_state: CandidateStatus = CandidateStatus.PROPOSED) -> None:
		super().__init__(initial_state, CandidateStatus, CANDIDATE_TRANSITIONS)


def structured_decision(
	decision: StructuredDecision,
	reason_code: str,
	*,
	budget_exhausted: bool = False,
	infrastructure_retry: bool = False,
) -> DecisionRecord:
	try:
		normalized = decision if isinstance(decision, StructuredDecision) else StructuredDecision(decision)
	except (TypeError, ValueError):
		raise ValueError("unknown structured decision: %r" % decision) from None
	if budget_exhausted and normalized != StructuredDecision.PAUSE_BUDGET:
		raise ValueError("budget exhaustion must map to pause_budget")
	if infrastructure_retry and normalized == StructuredDecision.PIVOT:
		raise ValueError("infrastructure retry cannot map to a scientific pivot")
	return DecisionRecord(decision=normalized, reason_code=reason_code)


__all__ = [
	"CANDIDATE_TRANSITIONS", "EXPERIMENT_TRANSITIONS", "HYPOTHESIS_TRANSITIONS", "RUN_TRANSITIONS",
	"CandidateStateMachine", "ExperimentStateMachine", "HypothesisStateMachine",
	"InvalidStateTransition", "ResearchRunStateMachine", "StateMachine",
	"structured_decision", "validate_transition",
]
