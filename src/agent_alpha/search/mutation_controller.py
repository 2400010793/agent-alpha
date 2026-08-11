from __future__ import annotations

from dataclasses import dataclass, field
from math import log, sqrt
from typing import Any

from agent_alpha.search.mutation_guard import prefix_node_count


MUTATION_AGENT_BY_FOCUS = {
    "event_definition_mutation": "EventDefinitionMutationAgent",
    "state_condition_mutation": "StateConditionMutationAgent",
    "response_shape_mutation": "ResponseShapeMutationAgent",
    "normalization_robustness_mutation": "NormalizationRobustnessMutationAgent",
    "time_structure_mutation": "TimeStructureMutationAgent",
    "refinement_simplification": "RefinementSimplificationAgent",
}
MUTATION_FOCUSES = tuple(MUTATION_AGENT_BY_FOCUS)


@dataclass(frozen=True)
class MutationPlan:
    parent_candidate: dict[str, Any]
    mutation_focus: str
    agent_name: str
    reason: str
    feedback_records: list[dict[str, Any]] = field(default_factory=list)
    memory_context: dict[str, Any] = field(default_factory=dict)


def _candidate_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("factor_id") or candidate.get("name") or "")


def _score_from_feedback(records: list[dict[str, Any]]) -> float:
    best = 0.0
    for record in records:
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        for key in ("daily_rankic", "global_rankic", "rankic", "daily_ic", "global_ic"):
            try:
                value = abs(float(metrics.get(key, 0.0)))
            except (TypeError, ValueError):
                value = 0.0
            best = max(best, value)
    return best


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result:
        return default
    return result


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _failure_penalty(records: list[dict[str, Any]]) -> float:
    text = _feedback_text(records)
    penalty = 0.0
    if any(term in text for term in ("compile", "field_leakage", "missing_factor_file", "render_validation_failed")):
        penalty += 1.0
    if any(term in text for term in ("complex", "cosmetic", "redundant")):
        penalty += 0.3
    if any(term in text for term in ("missing_rankic", "missing_finite_ratio", "missing_zero_ratio")):
        penalty += 0.05
    return penalty


def _is_hard_stop(records: list[dict[str, Any]]) -> bool:
    hard_modes = {"compile_failed", "field_leakage", "label_leakage", "unknown_field", "blocked_field", "render_validation_failed"}
    for record in records:
        modes = {str(item).casefold() for item in record.get("failure_modes", []) if str(item)}
        if modes & hard_modes:
            return True
    return False


def _search_value_from_score(score: float) -> float:
    if score >= 0.10:
        return 0.24
    if score >= 0.05:
        return 0.30
    if score >= 0.02:
        return 0.14
    if score > 0:
        return 0.04
    return 0.0


def _complexity_penalty(candidate: dict[str, Any]) -> float:
    prefix = candidate.get("prefix_expression")
    if prefix is None:
        return 0.0
    return max(0, prefix_node_count(prefix) - 5) * 0.03


def _priority(candidate: dict[str, Any], records: list[dict[str, Any]]) -> float:
    score = _score_from_feedback(records)
    attempts = _safe_int(candidate.get("mutation_attempt") or candidate.get("mutation_attempts") or 0)
    near_elite = max(0.0, 1.0 - abs(0.08 - score) / 0.08) if score > 0 else 0.0
    reviewed_bonus = 0.01 if records else 0.0
    return _search_value_from_score(score) + score + 0.1 * near_elite + reviewed_bonus - attempts * 0.04 - _complexity_penalty(candidate) - _failure_penalty(records)


def _feedback_text(records: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for record in records:
        parts.extend(str(item) for item in record.get("failure_modes", []) if item)
        for key in ("failure_type", "summary", "reason", "avoid_rule", "repair_hint"):
            value = str(record.get(key) or "")
            if value:
                parts.append(value)
    return " ".join(parts).casefold()


def _focus_from_feedback(records: list[dict[str, Any]]) -> tuple[str, str]:
    text = _feedback_text(records)
    if any(term in text for term in ("compile", "complex", "too complex", "redundant", "cosmetic", "sparse", "non-finite", "mostly zero", "low_finite_ratio", "high_zero_ratio")):
        return "refinement_simplification", "failure indicates invalid, sparse, complex, or cosmetic structure"
    if any(term in text for term in ("volume-only", "volume only", "false positive", "event")):
        return "event_definition_mutation", "failure suggests redefining the event trigger"
    if any(term in text for term in ("unstable", "oos", "turnover", "noisy", "raw_depth", "raw top-book", "liquidity", "spread")):
        return "state_condition_mutation", "failure suggests the factor needs a market-state or liquidity condition"
    if any(term in text for term in ("zscore", "rank(", "rank transform", "normalization", "scale", "safe_div", "raw subtraction")):
        return "normalization_robustness_mutation", "failure points to scaling or normalization robustness"
    if any(term in text for term in ("window", "horizon", "lag", "decay", "timing", "time")):
        return "time_structure_mutation", "failure points to timing or horizon mismatch"
    if any(term in text for term in ("weak_rankic", "weak rankic", "weak ic", "low ic", "low_rankic")):
        return "event_definition_mutation", "weak predictive signal suggests redefining the event"
    return "state_condition_mutation", "no specific failure mode matched; add a conservative market-state condition"


def _route_prior(records: list[dict[str, Any]], focus: str) -> tuple[float, str]:
    text = _feedback_text(records)
    if any(term in text for term in ("compile", "complex", "too complex", "redundant", "cosmetic", "sparse", "non-finite", "mostly zero", "low_finite_ratio", "high_zero_ratio")):
        return (0.20, "failure suggests simplification") if focus == "refinement_simplification" else (0.0, "")
    if any(term in text for term in ("volume-only", "volume only", "false positive", "event")):
        return (0.30, "failure suggests redefining the event trigger") if focus == "event_definition_mutation" else (0.0, "")
    if any(term in text for term in ("unstable", "oos", "turnover", "noisy", "raw_depth", "raw top-book", "liquidity", "spread")):
        return (0.15, "failure suggests market-state gating") if focus == "state_condition_mutation" else (0.0, "")
    if any(term in text for term in ("zscore", "rank(", "rank transform", "normalization", "scale", "safe_div", "raw subtraction")):
        return (0.15, "failure suggests normalization robustness") if focus == "normalization_robustness_mutation" else (0.0, "")
    if any(term in text for term in ("window", "horizon", "lag", "decay", "timing", "time")):
        return (0.15, "failure suggests timing repair") if focus == "time_structure_mutation" else (0.0, "")
    if any(term in text for term in ("weak_rankic", "weak rankic", "weak ic", "low ic", "low_rankic")):
        if focus == "event_definition_mutation":
            return 0.10, "weak predictive signal suggests event redefinition"
        if focus == "response_shape_mutation":
            return 0.08, "weak predictive signal may need response-shape change"
    return (0.02, "default high-frequency state gating prior") if focus == "state_condition_mutation" else (0.0, "")


def _lineage_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("lineage_id") or candidate.get("factor_id") or candidate.get("name") or "unknown_lineage")


def _arm_id(lineage_id: str, focus: str) -> str:
    return f"{lineage_id}:{focus}"


def _arm_record(arm_memory: Any, lineage_id: str, focus: str) -> dict[str, Any]:
    if not isinstance(arm_memory, dict):
        return {}
    arm_id = _arm_id(lineage_id, focus)
    record = arm_memory.get(arm_id)
    if isinstance(record, dict):
        return record
    nested = arm_memory.get(lineage_id)
    if isinstance(nested, dict) and isinstance(nested.get(focus), dict):
        return nested[focus]
    return {}


def _total_arm_trials(arm_memory: Any) -> int:
    if not isinstance(arm_memory, dict):
        return 0
    total = 0
    for value in arm_memory.values():
        if isinstance(value, dict) and "n_trials" in value:
            total += _safe_int(value.get("n_trials"))
        elif isinstance(value, dict):
            total += sum(_safe_int(item.get("n_trials")) for item in value.values() if isinstance(item, dict))
    return total


def _arm_bonus(arm_memory: Any, lineage_id: str, focus: str, *, exploration_c: float) -> tuple[float, dict[str, Any]]:
    record = _arm_record(arm_memory, lineage_id, focus)
    total_trials = _total_arm_trials(arm_memory)
    n_trials = _safe_int(record.get("n_trials"), 0)
    mean_reward = _safe_float(record.get("mean_reward"), 0.0)
    failure_count = _safe_int(record.get("failure_count"), 0)
    exploration = exploration_c * sqrt(log(total_trials + 1.0) / (n_trials + 1.0)) if total_trials > 0 else exploration_c
    bonus = mean_reward + exploration - failure_count * 0.01
    return bonus, {"n_trials": n_trials, "mean_reward": mean_reward, "failure_count": failure_count, "exploration_bonus": exploration}


def _lineage_trial_count(arm_memory: Any, lineage_id: str) -> int:
    if not isinstance(arm_memory, dict):
        return 0
    total = 0
    prefix = f"{lineage_id}:"
    for key, value in arm_memory.items():
        if isinstance(value, dict) and str(key).startswith(prefix):
            total += _safe_int(value.get("n_trials"), 0)
    nested = arm_memory.get(lineage_id)
    if isinstance(nested, dict):
        total += sum(_safe_int(item.get("n_trials"), 0) for item in nested.values() if isinstance(item, dict))
    return total


def _feedback_by_candidate(feedback_records: list[dict[str, Any]] | None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in feedback_records or []:
        factor_id = str(record.get("factor_id") or record.get("candidate_id") or record.get("id") or "")
        if factor_id:
            grouped.setdefault(factor_id, []).append(record)
    return grouped


def select_mutation_plan(
    candidates: list[dict[str, Any]],
    feedback_records: list[dict[str, Any]] | None = None,
    *,
    memory_context: dict[str, Any] | None = None,
    lineage_states: dict[str, Any] | None = None,
    arm_memory: dict[str, Any] | None = None,
    exploration_c: float = 0.03,
) -> MutationPlan | None:
    if not candidates:
        return None
    feedback = _feedback_by_candidate(feedback_records)
    lineage_states = lineage_states or {}
    scored: list[tuple[float, str, str, dict[str, Any], list[dict[str, Any]], dict[str, Any]]] = []
    for candidate in candidates:
        factor_id = _candidate_id(candidate)
        lineage_id = _lineage_id(candidate)
        state = lineage_states.get(lineage_id)
        if isinstance(state, dict) and state.get("stopped"):
            continue
        if getattr(state, "stopped", False):
            continue
        records = feedback.get(factor_id, [])
        if _is_hard_stop(records):
            continue
        parent_quality = _priority(candidate, records)
        lineage_trials = _lineage_trial_count(arm_memory, lineage_id)
        lineage_penalty = min(0.20, 0.025 * sqrt(lineage_trials)) if lineage_trials > 0 else 0.0
        for focus in MUTATION_FOCUSES:
            route_prior, route_reason = _route_prior(records, focus)
            arm_score, arm_stats = _arm_bonus(arm_memory, lineage_id, focus, exploration_c=exploration_c)
            focus_trials = _safe_int(arm_stats.get("n_trials"), 0)
            focus_repetition_penalty = min(0.18, 0.04 * sqrt(focus_trials)) if focus_trials > 0 else 0.0
            selector_score = parent_quality + route_prior + arm_score - lineage_penalty - focus_repetition_penalty
            scored.append(
                (
                    selector_score,
                    factor_id,
                    focus,
                    candidate,
                    records,
                    {
                        "selector_score": selector_score,
                        "parent_quality": parent_quality,
                        "route_prior": route_prior,
                        "route_reason": route_reason,
                        "arm_score": arm_score,
                        "arm_stats": arm_stats,
                        "lineage_trials": lineage_trials,
                        "lineage_penalty": lineage_penalty,
                        "focus_repetition_penalty": focus_repetition_penalty,
                        "arm_id": _arm_id(lineage_id, focus),
                    },
                )
            )
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, _, focus, parent, records, selector = scored[0]
    _, fallback_reason = _focus_from_feedback(records)
    reason = selector["route_reason"] or fallback_reason
    merged_memory_context = dict(memory_context or {})
    merged_memory_context["selector"] = selector
    return MutationPlan(
        parent_candidate=parent,
        mutation_focus=focus,
        agent_name=MUTATION_AGENT_BY_FOCUS[focus],
        reason=reason,
        feedback_records=records,
        memory_context=merged_memory_context,
    )


__all__ = ["MUTATION_AGENT_BY_FOCUS", "MUTATION_FOCUSES", "MutationPlan", "select_mutation_plan"]