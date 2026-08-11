from __future__ import annotations

from enum import Enum


class StringEnum(str, Enum):
	"""Enum whose serialized representation is its stable string value."""

	def __str__(self) -> str:
		return self.value


class ResearchRunStatus(StringEnum):
	CREATED = "created"
	VALIDATED = "validated"
	EVIDENCE_READY = "evidence_ready"
	HYPOTHESES_READY = "hypotheses_ready"
	APPROVAL_PENDING = "approval_pending"
	EXPERIMENTS_QUEUED = "experiments_queued"
	RUNNING = "running"
	REVIEW_PENDING = "review_pending"
	COMPLETED = "completed"
	PAUSED_EVIDENCE = "paused_evidence"
	PAUSED_BUDGET = "paused_budget"
	FAILED_RETRYABLE = "failed_retryable"
	FAILED_FINAL = "failed_final"


class HypothesisStatus(StringEnum):
	PROPOSED = "proposed"
	EVIDENCE_CHECKED = "evidence_checked"
	APPROVED = "approved"
	TESTING = "testing"
	SUPPORTED = "supported"
	REFUTED = "refuted"
	INCONCLUSIVE = "inconclusive"
	ABANDONED = "abandoned"


class ExperimentStatus(StringEnum):
	CREATED = "created"
	PREREGISTERED = "preregistered"
	QUEUED = "queued"
	RUNNING = "running"
	REVIEW_PENDING = "review_pending"
	COMPLETED = "completed"
	FAILED_RETRYABLE = "failed_retryable"
	FAILED_FINAL = "failed_final"


class CandidateStatus(StringEnum):
	PROPOSED = "proposed"
	VALIDATED = "validated"
	RENDERED = "rendered"
	COMPILED = "compiled"
	SCHEDULED = "scheduled"
	RUNNING = "running"
	EVALUATED = "evaluated"
	ACCEPTED = "accepted"
	REVISE = "revise"
	REJECTED = "rejected"
	FAILED = "failed"
	TIMED_OUT = "timed_out"
	SUPERSEDED = "superseded"


class RunAttemptStatus(StringEnum):
	CREATED = "created"
	QUEUED = "queued"
	RUNNING = "running"
	SUCCEEDED = "succeeded"
	FAILED_RETRYABLE = "failed_retryable"
	FAILED_FINAL = "failed_final"
	TIMED_OUT = "timed_out"


class ScientificVerdict(StringEnum):
	SUPPORTED = "supported"
	REFUTED = "refuted"
	INCONCLUSIVE = "inconclusive"


class OperationType(StringEnum):
	REPLICATION = "replication"
	BASELINE = "baseline"
	PRIMARY_TEST = "primary_test"
	ROBUSTNESS = "robustness"
	FALSIFICATION = "falsification"
	ABLATION = "ablation"
	PARAMETER_REFINE = "parameter_refine"
	MECHANISM_PIVOT = "mechanism_pivot"
	FACTOR_MUTATION = "factor_mutation"
	FACTOR_CROSSOVER = "factor_crossover"


class StructuredDecision(StringEnum):
	PROCEED = "proceed"
	REFINE = "refine"
	PIVOT = "pivot"
	REJECT = "reject"
	PAUSE_EVIDENCE = "pause_evidence"
	PAUSE_BUDGET = "pause_budget"
	INCONCLUSIVE = "inconclusive"


class GateStatus(StringEnum):
	ELIGIBLE = "eligible"
	STRUCTURAL_ONLY = "structural_only"
	NEEDS_DIGEST = "needs_digest"
	REJECTED = "rejected"


__all__ = [
	"CandidateStatus",
	"ExperimentStatus",
	"GateStatus",
	"HypothesisStatus",
	"OperationType",
	"ResearchRunStatus",
	"RunAttemptStatus",
	"ScientificVerdict",
	"StringEnum",
	"StructuredDecision",
]
