from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .ids import budget_id as make_budget_id


USAGE_FIELDS = (
	"hypotheses", "primary_candidates", "refine_or_pivot_rounds", "attempts",
	"compute_minutes", "llm_calls", "llm_tokens",
)


def _non_negative_number(value: Any, field_name: str, *, integer: bool = True) -> None:
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		raise ValueError("%s must be a non-negative number" % field_name)
	if not math.isfinite(float(value)) or value < 0:
		raise ValueError("%s must be non-negative and finite" % field_name)
	if integer and not isinstance(value, int):
		raise ValueError("%s must be a non-negative integer" % field_name)


@dataclass(frozen=True)
class BudgetSpec:
	max_hypotheses_per_graph: int = 3
	max_primary_candidates_per_hypothesis: int = 2
	max_refine_or_pivot_rounds: int = 2
	max_attempts_per_experiment: int = 3
	max_total_attempts: int = 30
	max_compute_minutes: float = 600.0
	max_llm_calls: int = 0
	max_llm_tokens: int = 0
	schema_version: str = "graph_research_budget_v1"
	budget_id: str = field(init=False)

	def __post_init__(self) -> None:
		for name in (
			"max_hypotheses_per_graph", "max_primary_candidates_per_hypothesis",
			"max_refine_or_pivot_rounds", "max_attempts_per_experiment", "max_total_attempts",
			"max_llm_calls", "max_llm_tokens",
		):
			_non_negative_number(getattr(self, name), name)
		_non_negative_number(self.max_compute_minutes, "max_compute_minutes", integer=False)
		if not isinstance(self.schema_version, str) or not self.schema_version.strip():
			raise ValueError("schema_version must be non-empty")
		object.__setattr__(self, "budget_id", make_budget_id(self.limit_payload()))

	def limit_payload(self) -> dict[str, Any]:
		return {
			"schema_version": self.schema_version,
			"max_hypotheses_per_graph": self.max_hypotheses_per_graph,
			"max_primary_candidates_per_hypothesis": self.max_primary_candidates_per_hypothesis,
			"max_refine_or_pivot_rounds": self.max_refine_or_pivot_rounds,
			"max_attempts_per_experiment": self.max_attempts_per_experiment,
			"max_total_attempts": self.max_total_attempts,
			"max_compute_minutes": self.max_compute_minutes,
			"max_llm_calls": self.max_llm_calls,
			"max_llm_tokens": self.max_llm_tokens,
		}

	def to_dict(self) -> dict[str, Any]:
		return dict(self.limit_payload(), budget_id=self.budget_id)


@dataclass(frozen=True)
class BudgetUsage:
	hypotheses: int = 0
	primary_candidates: int = 0
	refine_or_pivot_rounds: int = 0
	attempts: int = 0
	compute_minutes: float = 0.0
	llm_calls: int = 0
	llm_tokens: int = 0

	def __post_init__(self) -> None:
		for name in ("hypotheses", "primary_candidates", "refine_or_pivot_rounds", "attempts", "llm_calls", "llm_tokens"):
			_non_negative_number(getattr(self, name), name)
		_non_negative_number(self.compute_minutes, "compute_minutes", integer=False)

	def plus(self, other: "BudgetUsage") -> "BudgetUsage":
		if not isinstance(other, BudgetUsage):
			raise TypeError("other must be BudgetUsage")
		return BudgetUsage(**{name: getattr(self, name) + getattr(other, name) for name in USAGE_FIELDS})

	def to_dict(self) -> dict[str, Any]:
		return {name: getattr(self, name) for name in USAGE_FIELDS}

	@property
	def is_zero(self) -> bool:
		return all(getattr(self, name) == 0 for name in USAGE_FIELDS)


@dataclass(frozen=True)
class BudgetDecision:
	allowed: bool
	reason_codes: tuple[str, ...]
	usage: BudgetUsage
	idempotent_replay: bool = False

	@property
	def pause_budget(self) -> bool:
		return not self.allowed

	def to_dict(self) -> dict[str, Any]:
		return {
			"allowed": self.allowed, "reason_codes": list(self.reason_codes),
			"usage": self.usage.to_dict(), "idempotent_replay": self.idempotent_replay,
		}


class BudgetLedger:
	"""In-memory, atomic and idempotent accounting for one graph research run."""

	def __init__(self, spec: BudgetSpec) -> None:
		if not isinstance(spec, BudgetSpec):
			raise TypeError("spec must be BudgetSpec")
		self._spec = spec
		self._usage = BudgetUsage()
		self._events: dict[str, tuple[BudgetUsage, Optional[str], Optional[str]]] = {}
		self._hypothesis_usage: dict[str, BudgetUsage] = {}
		self._experiment_usage: dict[str, BudgetUsage] = {}

	@property
	def spec(self) -> BudgetSpec:
		return self._spec

	@property
	def usage(self) -> BudgetUsage:
		return self._usage

	@property
	def event_ids(self) -> frozenset[str]:
		return frozenset(self._events)

	def consume(
		self,
		event_id: str,
		usage: Optional[BudgetUsage] = None,
		*,
		hypothesis_id: Optional[str] = None,
		experiment_id: Optional[str] = None,
		**increments: Any,
	) -> BudgetDecision:
		if not isinstance(event_id, str) or not event_id.strip():
			raise ValueError("event_id must be a non-empty string")
		if usage is not None and increments:
			raise ValueError("provide BudgetUsage or keyword increments, not both")
		if usage is None:
			unknown = set(increments) - set(USAGE_FIELDS)
			if unknown:
				raise ValueError("unknown budget usage fields: %s" % sorted(unknown))
			usage = BudgetUsage(**increments)
		if not isinstance(usage, BudgetUsage):
			raise TypeError("usage must be BudgetUsage")
		if usage.is_zero:
			raise ValueError("usage event must consume at least one budget category")
		hypothesis_id = self._normalize_scope(hypothesis_id, "hypothesis_id")
		experiment_id = self._normalize_scope(experiment_id, "experiment_id")
		event_key = event_id.strip()
		existing = self._events.get(event_key)
		if existing is not None:
			if existing != (usage, hypothesis_id, experiment_id):
				return BudgetDecision(False, ("event_id_conflict",), self._usage)
			return BudgetDecision(True, ("duplicate_event",), self._usage, idempotent_replay=True)

		reasons = self._limit_reasons(usage, hypothesis_id=hypothesis_id, experiment_id=experiment_id)
		if reasons:
			return BudgetDecision(False, tuple(sorted(reasons)), self._usage)

		# All checks precede these assignments, so an over-limit event changes nothing.
		self._usage = self._usage.plus(usage)
		if hypothesis_id is not None:
			self._hypothesis_usage[hypothesis_id] = self._hypothesis_usage.get(hypothesis_id, BudgetUsage()).plus(usage)
		if experiment_id is not None:
			self._experiment_usage[experiment_id] = self._experiment_usage.get(experiment_id, BudgetUsage()).plus(usage)
		self._events[event_key] = (usage, hypothesis_id, experiment_id)
		return BudgetDecision(True, ("within_budget",), self._usage)

	def usage_for_hypothesis(self, hypothesis_id: str) -> BudgetUsage:
		return self._hypothesis_usage.get(self._normalize_scope(hypothesis_id, "hypothesis_id"), BudgetUsage())

	def usage_for_experiment(self, experiment_id: str) -> BudgetUsage:
		return self._experiment_usage.get(self._normalize_scope(experiment_id, "experiment_id"), BudgetUsage())

	def snapshot(self) -> Mapping[str, Any]:
		return MappingProxyType({
			"budget_id": self.spec.budget_id,
			"usage": MappingProxyType(self.usage.to_dict()),
			"event_ids": tuple(sorted(self._events)),
		})

	@staticmethod
	def _normalize_scope(value: Optional[str], field_name: str) -> Optional[str]:
		if value is None:
			return None
		if not isinstance(value, str) or not value.strip():
			raise ValueError("%s must be non-empty when supplied" % field_name)
		return value.strip()

	def _limit_reasons(
		self,
		increment: BudgetUsage,
		*,
		hypothesis_id: Optional[str],
		experiment_id: Optional[str],
	) -> list[str]:
		projected = self._usage.plus(increment)
		reasons = []
		if projected.hypotheses > self.spec.max_hypotheses_per_graph:
			reasons.append("max_hypotheses_per_graph_exceeded")
		if projected.attempts > self.spec.max_total_attempts:
			reasons.append("max_total_attempts_exceeded")
		if projected.compute_minutes > self.spec.max_compute_minutes:
			reasons.append("max_compute_minutes_exceeded")
		if projected.llm_calls > self.spec.max_llm_calls:
			reasons.append("max_llm_calls_exceeded")
		if projected.llm_tokens > self.spec.max_llm_tokens:
			reasons.append("max_llm_tokens_exceeded")

		if increment.primary_candidates:
			if hypothesis_id is None:
				reasons.append("hypothesis_scope_required")
			elif self.usage_for_hypothesis(hypothesis_id).primary_candidates + increment.primary_candidates > self.spec.max_primary_candidates_per_hypothesis:
				reasons.append("max_primary_candidates_per_hypothesis_exceeded")
		if increment.refine_or_pivot_rounds:
			if hypothesis_id is None:
				reasons.append("hypothesis_scope_required")
			elif self.usage_for_hypothesis(hypothesis_id).refine_or_pivot_rounds + increment.refine_or_pivot_rounds > self.spec.max_refine_or_pivot_rounds:
				reasons.append("max_refine_or_pivot_rounds_exceeded")
		if increment.attempts:
			if experiment_id is None:
				reasons.append("experiment_scope_required")
			elif self.usage_for_experiment(experiment_id).attempts + increment.attempts > self.spec.max_attempts_per_experiment:
				reasons.append("max_attempts_per_experiment_exceeded")
		return reasons


__all__ = ["BudgetDecision", "BudgetLedger", "BudgetSpec", "BudgetUsage", "USAGE_FIELDS"]
