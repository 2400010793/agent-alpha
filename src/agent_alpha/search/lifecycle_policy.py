from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any


SCORE_KEYS = ("daily_rankic", "global_rankic", "rankic", "daily_ic", "global_ic")
HARD_FAILURE_MODES = {"compile_failed", "validator_failed", "field_leakage", "missing_factor_file", "render_validation_failed"}


@dataclass(frozen=True)
class LifecycleThresholds:
    elite_score: float = 0.08
    bad_score: float = 0.03
    min_improvement_margin: float = 0.005
    bad_patience_generations: int = 2
    mutation_attempt_penalty: float = 0.04


@dataclass
class LineageState:
    lineage_id: str
    best_score: float = 0.0
    best_factor_id: str = ""
    failed_generations: int = 0
    stopped: bool = False
    stop_reason: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:
        return None
    return result


def factor_score(metrics: dict[str, Any] | None) -> float | None:
    metrics = metrics or {}
    for key in SCORE_KEYS:
        value = _float_or_none(metrics.get(key))
        if value is not None:
            return abs(value)
    return None


def factor_id(candidate: dict[str, Any] | None, review: dict[str, Any] | None = None) -> str:
    candidate = candidate or {}
    review = review or {}
    return str(candidate.get("factor_id") or candidate.get("name") or review.get("factor_id") or review.get("factor_name") or "")


def review_metrics(review: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(review, dict):
        return {}
    metrics = review.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def is_hard_failure(review: dict[str, Any] | None) -> bool:
    modes = set(str(item) for item in (review or {}).get("failure_modes", []))
    return bool(modes & HARD_FAILURE_MODES)


def should_freeze_for_library(review: dict[str, Any], *, thresholds: LifecycleThresholds = LifecycleThresholds()) -> bool:
    if str(review.get("decision") or "") != "accept":
        return False
    if is_hard_failure(review):
        return False
    score = factor_score(review_metrics(review))
    return score is not None and score >= thresholds.elite_score


def child_exceeds_parent(
    child_review: dict[str, Any],
    parent_review: dict[str, Any] | None,
    *,
    thresholds: LifecycleThresholds = LifecycleThresholds(),
) -> bool:
    if is_hard_failure(child_review):
        return False
    child_score = factor_score(review_metrics(child_review))
    if child_score is None:
        return False
    parent_score = factor_score(review_metrics(parent_review)) or 0.0
    return child_score >= thresholds.bad_score and child_score >= parent_score + thresholds.min_improvement_margin


def parent_should_freeze_after_children(
    parent_review: dict[str, Any],
    child_reviews: list[dict[str, Any]],
    *,
    thresholds: LifecycleThresholds = LifecycleThresholds(),
) -> bool:
    if not should_freeze_for_library(parent_review, thresholds=thresholds):
        return False
    return not any(child_exceeds_parent(child_review, parent_review, thresholds=thresholds) for child_review in child_reviews)


def parent_should_enter_library(
    parent_review: dict[str, Any],
    child_reviews: list[dict[str, Any]],
    *,
    thresholds: LifecycleThresholds = LifecycleThresholds(),
) -> bool:
    """Admit only the challenged parent, never the child challenger."""
    return parent_should_freeze_after_children(parent_review, child_reviews, thresholds=thresholds)


def best_child_for_continuation(
    parent_review: dict[str, Any],
    child_reviews: list[dict[str, Any]],
    *,
    thresholds: LifecycleThresholds = LifecycleThresholds(),
) -> dict[str, Any] | None:
    challengers = [review for review in child_reviews if child_exceeds_parent(review, parent_review, thresholds=thresholds)]
    if not challengers:
        return None
    return max(challengers, key=lambda review: factor_score(review_metrics(review)) or 0.0)


def lineage_id_for_candidate(candidate: dict[str, Any]) -> str:
    explicit = candidate.get("lineage_id")
    if explicit:
        return str(explicit)
    parent_ids = candidate.get("parent_ids")
    if isinstance(parent_ids, list) and parent_ids:
        return str(parent_ids[0])
    return str(candidate.get("factor_id") or candidate.get("name") or "unknown_lineage")


def update_lineage_state(
    state: LineageState,
    child_reviews: list[dict[str, Any]],
    *,
    thresholds: LifecycleThresholds = LifecycleThresholds(),
) -> LineageState:
    best_child_score = 0.0
    best_child_id = ""
    generation_has_progress = False
    for review in child_reviews:
        score = factor_score(review_metrics(review)) or 0.0
        if score > best_child_score:
            best_child_score = score
            best_child_id = factor_id(None, review)
        if score >= thresholds.bad_score:
            generation_has_progress = True
        state.history.append({"factor_id": factor_id(None, review), "score": score, "decision": review.get("decision"), "failure_modes": review.get("failure_modes", [])})
    if best_child_score > state.best_score:
        state.best_score = best_child_score
        state.best_factor_id = best_child_id
    if generation_has_progress:
        state.failed_generations = 0
    else:
        state.failed_generations += 1
    if state.failed_generations >= thresholds.bad_patience_generations and state.best_score < thresholds.bad_score:
        state.stopped = True
        state.stop_reason = "all_children_below_bad_threshold_after_patience"
    return state


def should_mark_lineage_bad(state: LineageState, *, thresholds: LifecycleThresholds = LifecycleThresholds()) -> bool:
    return state.stopped and state.best_score < thresholds.bad_score


def mutation_parent_status(review: dict[str, Any], *, thresholds: LifecycleThresholds = LifecycleThresholds()) -> str:
    if is_hard_failure(review):
        return "invalid_stopped"
    score = factor_score(review_metrics(review))
    if should_freeze_for_library(review, thresholds=thresholds):
        return "elite_frozen"
    if score is None:
        return "weak_retry"
    if score < thresholds.bad_score:
        return "weak_retry"
    if score < thresholds.elite_score:
        return "promising_continue"
    return "elite_candidate_needs_accept_review"


def eligible_for_mutation(review: dict[str, Any], *, thresholds: LifecycleThresholds = LifecycleThresholds()) -> bool:
    return mutation_parent_status(review, thresholds=thresholds) in {"promising_continue", "weak_retry"}


def mutation_attempt_count(candidate: dict[str, Any], state: LineageState | None = None) -> int:
    explicit = candidate.get("mutation_attempt") or candidate.get("mutation_attempts")
    try:
        if explicit is not None:
            return int(explicit)
    except (TypeError, ValueError):
        pass
    if state is not None:
        return len(state.history)
    return 0


def mutation_parent_priority(
    candidate: dict[str, Any],
    review: dict[str, Any],
    *,
    state: LineageState | None = None,
    thresholds: LifecycleThresholds = LifecycleThresholds(),
) -> float:
    if not eligible_for_mutation(review, thresholds=thresholds):
        return float("-inf")
    score = factor_score(review_metrics(review)) or 0.0
    attempts = mutation_attempt_count(candidate, state)
    # XALPHA-style pressure: near-miss candidates are valuable; repeated failures become less valuable.
    if score >= thresholds.bad_score:
        potential = 1.0 - min(1.0, abs(thresholds.elite_score - score) / max(thresholds.elite_score, 1e-12))
    else:
        potential = 0.25 * (score / max(thresholds.bad_score, 1e-12))
    return potential - attempts * thresholds.mutation_attempt_penalty


def select_mutation_parents(
    candidates: list[dict[str, Any]],
    reviews_by_factor_id: dict[str, dict[str, Any]],
    *,
    lineage_states: dict[str, LineageState] | None = None,
    max_parents: int = 5,
    thresholds: LifecycleThresholds = LifecycleThresholds(),
) -> list[dict[str, Any]]:
    lineage_states = lineage_states or {}
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for candidate in candidates:
        fid = factor_id(candidate)
        review = reviews_by_factor_id.get(fid)
        if not review:
            continue
        lineage_id = lineage_id_for_candidate(candidate)
        priority = mutation_parent_priority(candidate, review, state=lineage_states.get(lineage_id), thresholds=thresholds)
        if priority == float("-inf"):
            continue
        scored.append((priority, fid, candidate))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [candidate for _, _, candidate in scored[: max(0, max_parents)]]


def novelty_key(candidate: dict[str, Any]) -> str:
    payload = {
        "mechanism_tags": sorted(str(tag) for tag in candidate.get("mechanism_tags", [])),
        "fields": sorted(str(field) for field in candidate.get("fields", [])),
        "windows": sorted(int(window) for window in candidate.get("windows", []) if str(window).lstrip("-").isdigit()),
        "prefix_expression": candidate.get("prefix_expression"),
        "direction": candidate.get("direction", "unknown"),
    }
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_good_feedback(review: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": "GOOD",
        "factor_id": factor_id(candidate, review),
        "reason": "accepted_above_elite_threshold_and_frozen",
        "reusable_principle": str(candidate.get("economic_rationale") or review.get("economic_logic_summary") or "Elite factor passed admission threshold."),
        "mechanism_tags": list(candidate.get("mechanism_tags", [])),
        "prefix_expression": candidate.get("prefix_expression"),
        "metrics": review_metrics(review),
        "freeze": True,
        "do_not_mutate": True,
        "novelty_key": novelty_key(candidate),
    }


def build_lineage_bad_feedback(state: LineageState) -> dict[str, Any]:
    return {
        "label": "BAD",
        "factor_id": state.lineage_id,
        "failure_type": "lineage_failed_to_reach_bad_threshold",
        "reason": state.stop_reason or "lineage failed to improve",
        "avoid_rule": "Do not keep mutating this lineage unless the mechanism is materially redefined; repeated children stayed below IC/RankIC 0.03.",
        "lineage_id": state.lineage_id,
        "best_score": state.best_score,
        "best_factor_id": state.best_factor_id,
        "history": list(state.history),
    }


__all__ = [
    "LifecycleThresholds",
    "LineageState",
    "best_child_for_continuation",
    "build_good_feedback",
    "build_lineage_bad_feedback",
    "child_exceeds_parent",
    "eligible_for_mutation",
    "factor_score",
    "lineage_id_for_candidate",
    "mutation_attempt_count",
    "mutation_parent_status",
    "mutation_parent_priority",
    "novelty_key",
    "parent_should_enter_library",
    "parent_should_freeze_after_children",
    "select_mutation_parents",
    "should_freeze_for_library",
    "should_mark_lineage_bad",
    "update_lineage_state",
]