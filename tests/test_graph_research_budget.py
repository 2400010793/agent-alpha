from __future__ import annotations

import pytest

from agent_alpha.graph_research.budget import BudgetLedger, BudgetSpec, BudgetUsage


def _ledger() -> BudgetLedger:
	return BudgetLedger(BudgetSpec(
		max_hypotheses_per_graph=3, max_primary_candidates_per_hypothesis=2,
		max_refine_or_pivot_rounds=2, max_attempts_per_experiment=2,
		max_total_attempts=3, max_compute_minutes=10, max_llm_calls=2, max_llm_tokens=100,
	))


def test_normal_consumption_exact_limit_and_idempotent_replay() -> None:
	ledger = _ledger()
	first = ledger.consume("hypotheses", BudgetUsage(hypotheses=3))
	assert first.allowed and ledger.usage.hypotheses == 3
	replay = ledger.consume("hypotheses", BudgetUsage(hypotheses=3))
	assert replay.allowed and replay.idempotent_replay
	assert ledger.usage.hypotheses == 3


def test_over_limit_is_atomic_and_returns_stable_reason() -> None:
	ledger = _ledger()
	ledger.consume("compute_1", BudgetUsage(compute_minutes=8))
	before = ledger.usage
	decision = ledger.consume("compute_2", BudgetUsage(compute_minutes=3, llm_calls=1))
	assert not decision.allowed and decision.pause_budget
	assert decision.reason_codes == ("max_compute_minutes_exceeded",)
	assert ledger.usage == before
	assert "compute_2" not in ledger.event_ids


def test_scoped_retry_and_scientific_branch_budgets_do_not_cross() -> None:
	ledger = _ledger()
	assert ledger.consume("attempt_a1", attempts=1, experiment_id="exp_a").allowed
	assert ledger.consume("attempt_a2", attempts=1, experiment_id="exp_a").allowed
	assert not ledger.consume("attempt_a3", attempts=1, experiment_id="exp_a").allowed
	assert ledger.consume("candidate_h1", primary_candidates=2, hypothesis_id="hyp_1").allowed
	assert ledger.consume("candidate_h2", primary_candidates=2, hypothesis_id="hyp_2").allowed
	assert ledger.usage.attempts == 2
	assert ledger.usage.primary_candidates == 4


def test_different_budget_categories_are_independent() -> None:
	ledger = _ledger()
	assert ledger.consume("llm", llm_calls=2, llm_tokens=100).allowed
	assert ledger.consume("compute", compute_minutes=10).allowed
	assert ledger.usage.llm_calls == 2
	assert ledger.usage.compute_minutes == 10


@pytest.mark.parametrize("usage", [BudgetUsage, lambda: BudgetUsage(attempts=-1), lambda: BudgetUsage(compute_minutes=float("nan"))])
def test_invalid_usage_is_rejected(usage) -> None:
	if usage is BudgetUsage:
		with pytest.raises(ValueError, match="at least one"):
			_ledger().consume("empty", usage())
	else:
		with pytest.raises(ValueError):
			usage()


def test_event_id_conflict_does_not_mutate_ledger() -> None:
	ledger = _ledger()
	ledger.consume("same", llm_calls=1)
	before = ledger.usage
	decision = ledger.consume("same", llm_calls=2)
	assert not decision.allowed
	assert decision.reason_codes == ("event_id_conflict",)
	assert ledger.usage == before
