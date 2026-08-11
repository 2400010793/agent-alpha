"""Offline graph-conditioned research domain and control-plane primitives."""

from .budget import BudgetDecision, BudgetLedger, BudgetSpec, BudgetUsage
from .graph_gate import GraphResearchGate
from .checkpoint import CheckpointCorruptionError, ResearchCheckpointStore
from .events import ResearchEvent, validate_event_chain
from .ids import (
	NO_EVIDENCE,
	canonical_json,
	content_hash,
	deterministic_id,
	experiment_id,
	experiment_review_id,
	hypothesis_id,
	research_run_id,
	run_attempt_id,
)
from .models import (
	DecisionRecord,
	ExperimentNodeV1,
	ExperimentReviewV1,
	GateDecision,
	GraphResearchContext,
	HypothesisNodeV1,
	RunAttemptV1,
)
from .orchestrator import GraphResearchOrchestrator, IntakeResult, ResearchRunSnapshot
from .review import AcceptanceRuleError, build_rule_based_review, evaluate_acceptance_rule
from .state_machine import (
	CandidateStateMachine,
	ExperimentStateMachine,
	HypothesisStateMachine,
	InvalidStateTransition,
	ResearchRunStateMachine,
	structured_decision,
)
from .states import (
	CandidateStatus,
	ExperimentStatus,
	GateStatus,
	HypothesisStatus,
	OperationType,
	ResearchRunStatus,
	RunAttemptStatus,
	ScientificVerdict,
	StructuredDecision,
)


__all__ = [
	"BudgetDecision", "BudgetLedger", "BudgetSpec", "BudgetUsage", "CandidateStateMachine",
	"AcceptanceRuleError", "CandidateStatus", "DecisionRecord", "ExperimentNodeV1", "ExperimentReviewV1", "ExperimentStateMachine",
	"ExperimentStatus", "GateDecision", "GateStatus", "GraphResearchContext",
	"GraphResearchGate", "GraphResearchOrchestrator", "HypothesisNodeV1", "HypothesisStateMachine", "HypothesisStatus",
	"CheckpointCorruptionError", "IntakeResult", "ResearchCheckpointStore", "ResearchEvent", "ResearchRunSnapshot",
	"InvalidStateTransition", "NO_EVIDENCE", "OperationType", "ResearchRunStateMachine",
	"ResearchRunStatus", "RunAttemptStatus", "RunAttemptV1", "ScientificVerdict", "StructuredDecision",
	"build_rule_based_review", "canonical_json", "content_hash", "deterministic_id", "evaluate_acceptance_rule", "experiment_id", "experiment_review_id", "hypothesis_id",
	"research_run_id", "run_attempt_id", "structured_decision", "validate_event_chain",
]
