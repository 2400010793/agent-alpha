from __future__ import annotations

from agent_alpha.search.lifecycle_policy import (
    LifecycleThresholds,
    LineageState,
    best_child_for_continuation,
    build_good_feedback,
    build_lineage_bad_feedback,
    child_exceeds_parent,
    eligible_for_mutation,
    mutation_parent_status,
    parent_should_enter_library,
    parent_should_freeze_after_children,
    select_mutation_parents,
    should_freeze_for_library,
    should_mark_lineage_bad,
    update_lineage_state,
)


def _review(factor_id: str, score: float, *, decision: str = "accept", failure_modes: list[str] | None = None) -> dict:
    return {
        "factor_id": factor_id,
        "factor_name": factor_id,
        "decision": decision,
        "metrics": {"daily_rankic": score, "finite_ratio": 0.95, "zero_ratio": 0.2},
        "failure_modes": failure_modes or [],
        "economic_logic_summary": "clear mechanism",
    }


def _candidate(factor_id: str) -> dict:
    return {
        "factor_id": factor_id,
        "name": factor_id,
        "prefix_expression": ["zscore", "volume", 60],
        "fields": ["volume"],
        "windows": [60],
        "direction": "positive",
        "mechanism_tags": ["trade_impact"],
        "economic_rationale": "Volume pressure mechanism.",
    }


def test_elite_accept_does_not_freeze_and_builds_good_feedback() -> None:
    review = _review("elite", 0.081)
    candidate = _candidate("elite")

    assert not should_freeze_for_library(review)
    assert mutation_parent_status(review) == "elite_continue"
    assert eligible_for_mutation(review)
    feedback = build_good_feedback(review, candidate)
    assert feedback["label"] == "GOOD"
    assert feedback["freeze"] is True
    assert feedback["do_not_mutate"] is True


def test_accept_below_elite_threshold_does_not_enter_library() -> None:
    review = _review("near", 0.05)

    assert not should_freeze_for_library(review)
    assert mutation_parent_status(review) == "promising_continue"
    assert eligible_for_mutation(review)


def test_child_challenges_parent_but_never_enters_library_directly() -> None:
    parent = _review("parent", 0.085, decision="accept")
    weak_child = _review("weak_child", 0.061, decision="revise")
    better_child = _review("better_child", 0.091, decision="accept")
    elite_but_not_better_child = _review("elite_not_better", 0.081, decision="accept")

    assert not child_exceeds_parent(weak_child, parent)
    assert child_exceeds_parent(better_child, parent)
    assert not child_exceeds_parent(elite_but_not_better_child, parent)
    assert best_child_for_continuation(parent, [weak_child, better_child, elite_but_not_better_child]) == better_child
    assert not parent_should_enter_library(parent, [better_child])


def test_parent_does_not_freeze_when_children_do_not_exceed_it() -> None:
    parent = _review("parent", 0.09, decision="accept")
    children = [_review("child_1", 0.04, decision="revise"), _review("child_2", 0.081, decision="accept")]

    assert not parent_should_freeze_after_children(parent, children)
    assert not parent_should_enter_library(parent, children)
    assert not parent_should_freeze_after_children(parent, [_review("child_3", 0.096, decision="accept")])


def test_hard_failure_is_invalid_stopped_even_with_high_score() -> None:
    review = _review("bad_impl", 0.2, failure_modes=["compile_failed"])

    assert not should_freeze_for_library(review)
    assert mutation_parent_status(review) == "invalid_stopped"
    assert not eligible_for_mutation(review)


def test_lineage_becomes_bad_after_repeated_children_below_threshold() -> None:
    thresholds = LifecycleThresholds(bad_patience_generations=2)
    state = LineageState(lineage_id="lineage_a")

    update_lineage_state(state, [_review("child_1", 0.01, decision="revise"), _review("child_2", 0.02, decision="revise")], thresholds=thresholds)
    assert not should_mark_lineage_bad(state, thresholds=thresholds)
    update_lineage_state(state, [_review("child_3", 0.01, decision="revise"), _review("child_4", 0.029, decision="revise")], thresholds=thresholds)

    assert should_mark_lineage_bad(state, thresholds=thresholds)
    feedback = build_lineage_bad_feedback(state)
    assert feedback["label"] == "BAD"
    assert feedback["failure_type"] == "lineage_failed_to_reach_bad_threshold"


def test_lineage_failure_count_resets_when_child_reaches_bad_threshold() -> None:
    state = LineageState(lineage_id="lineage_b")
    update_lineage_state(state, [_review("child_1", 0.01, decision="revise")])
    assert state.failed_generations == 1

    update_lineage_state(state, [_review("child_2", 0.031, decision="revise")])

    assert state.failed_generations == 0
    assert not state.stopped


def test_select_mutation_parents_prioritizes_near_miss_and_penalizes_attempts() -> None:
    candidates = [
        {**_candidate("weak"), "mutation_attempt": 0},
        {**_candidate("near"), "mutation_attempt": 0},
        {**_candidate("repeated"), "mutation_attempt": 20},
        {**_candidate("elite"), "mutation_attempt": 0},
    ]
    reviews = {
        "weak": _review("weak", 0.01, decision="revise"),
        "near": _review("near", 0.06, decision="revise"),
        "repeated": _review("repeated", 0.061, decision="revise"),
        "elite": _review("elite", 0.09, decision="accept"),
    }

    selected = select_mutation_parents(candidates, reviews, max_parents=3)

    assert [item["factor_id"] for item in selected] == ["elite", "near", "weak"]