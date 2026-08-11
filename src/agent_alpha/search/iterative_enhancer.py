from __future__ import annotations

from typing import Any

from agent_alpha.llm.client import LLMClient
from agent_alpha.memory.function_memory import search_function_memory
from agent_alpha.memory.specialist_memory import search_specialist_memory
from agent_alpha.memory.transfer_memory import search_transfer_memory
from agent_alpha.search.factor_mutation import generate_factor_mutations
from agent_alpha.search.memory_summarizer import write_specialist_mutation_memory
from agent_alpha.search.mutation_controller import select_mutation_plan


MAX_MUTATION_CONTEXT_CHARS = 32000


def _feedback_id(record: dict[str, Any]) -> str:
    return str(record.get("factor_id") or record.get("candidate_id") or record.get("id") or "")


def _feedback_by_candidate(feedback_records: list[dict[str, Any]] | None) -> dict[str, list[dict[str, Any]]]:
    feedback: dict[str, list[dict[str, Any]]] = {}
    for record in feedback_records or []:
        factor_id = _feedback_id(record)
        if not factor_id:
            continue
        feedback.setdefault(factor_id, []).append(record)
    return feedback


def _feedback_summary(records: list[dict[str, Any]]) -> tuple[str, str, dict[str, Any]]:
    effective: list[str] = []
    ineffective: list[str] = []
    metrics: dict[str, Any] = {}
    for record in records:
        label = str(record.get("label") or record.get("decision") or "").upper()
        text = str(record.get("summary") or record.get("reason") or record.get("avoid_rule") or record.get("repair_hint") or "")
        if label == "GOOD":
            effective.append(text)
        elif label in {"BAD", "REVISE", "REJECT"}:
            ineffective.append(text)
        if isinstance(record.get("metrics"), dict):
            metrics.update(record["metrics"])
    return "\n".join(item for item in effective if item), "\n".join(item for item in ineffective if item), metrics


def _metric_score(records: list[dict[str, Any]]) -> float | None:
    for record in records:
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        for key in ("daily_rankic", "global_rankic", "rankic", "daily_ic", "global_ic"):
            try:
                return abs(float(metrics[key])) if key in metrics else None
            except (TypeError, ValueError):
                return None
    return None


def _lineage_context(parent: dict[str, Any], candidates: list[dict], feedback_records: list[dict] | None) -> dict[str, Any]:
    by_id = {str(candidate.get("factor_id") or candidate.get("name") or ""): candidate for candidate in candidates}
    feedback = _feedback_by_candidate(feedback_records)
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current: dict[str, Any] | None = parent
    while isinstance(current, dict):
        factor_id = str(current.get("factor_id") or current.get("name") or "")
        if not factor_id or factor_id in seen:
            break
        seen.add(factor_id)
        records = feedback.get(factor_id, [])
        metrics: dict[str, Any] = {}
        for record in records:
            if isinstance(record.get("metrics"), dict):
                metrics.update(record["metrics"])
        chain.append(
            {
                "factor_id": factor_id,
                "prefix_expression": current.get("prefix_expression"),
                "fields": list(current.get("fields") or []),
                "windows": list(current.get("windows") or []),
                "score": _metric_score(records),
                "metrics": metrics,
            }
        )
        parent_ids = current.get("parent_ids")
        if not isinstance(parent_ids, list) or not parent_ids:
            break
        current = by_id.get(str(parent_ids[0]))
    chain.reverse()
    for index, item in enumerate(chain):
        previous_score = chain[index - 1].get("score") if index > 0 else None
        score = item.get("score")
        item["delta_from_previous"] = score - previous_score if score is not None and previous_score is not None else None
    return {
        "root_factor_id": chain[0]["factor_id"] if chain else "",
        "parent_factor_id": str(parent.get("factor_id") or parent.get("name") or ""),
        "ancestor_count": max(0, len(chain) - 1),
        "chain": chain,
    }


def _compact_record(record: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: record[key] for key in keys if key in record and record[key] not in ("", None, [], {})}


def _bounded_context(context: dict[str, Any], *, max_chars: int = MAX_MUTATION_CONTEXT_CHARS) -> dict[str, Any]:
    # Keep deterministic priority: lineage, specialist, transfer, then function memory.
    bounded = {
        "lineage_context": context.get("lineage_context", {}),
        "specialist_memory": list(context.get("specialist_memory", [])),
        "transfer_memory": list(context.get("transfer_memory", [])),
        "function_memory": list(context.get("function_memory", [])),
        "budget": {"max_chars": max_chars, "approx_max_tokens": max_chars // 4},
    }
    import json

    while len(json.dumps(bounded, ensure_ascii=False, default=str)) > max_chars:
        for key in ("function_memory", "transfer_memory", "specialist_memory"):
            if bounded[key]:
                bounded[key].pop()
                break
        else:
            chain = bounded["lineage_context"].get("chain") if isinstance(bounded.get("lineage_context"), dict) else None
            if isinstance(chain, list) and len(chain) > 1:
                chain.pop(0)
                bounded["lineage_context"]["ancestor_count"] = max(0, len(chain) - 1)
            else:
                break
    bounded["budget"]["actual_chars"] = len(json.dumps(bounded, ensure_ascii=False, default=str))
    return bounded


def _mutation_memory_context(plan, candidates: list[dict], feedback_records: list[dict] | None) -> dict[str, Any]:
    query_items = [plan.mutation_focus, *plan.parent_candidate.get("mechanism_tags", []), *plan.parent_candidate.get("fields", [])]
    memory_query = " ".join(str(item) for item in query_items if str(item))
    lineage_context = _lineage_context(plan.parent_candidate, candidates, feedback_records)
    specialist_records = [
        _compact_record(record, ("label", "mutation_focus", "parent_factor_id", "child_factor_id", "summary", "reason", "mechanism_tags", "fields"))
        for record in search_specialist_memory(plan.agent_name, memory_query, limit=4)
    ]
    function_records = [
        _compact_record(record, ("label", "function_pattern", "asl_ops", "fields", "windows", "summary", "avoid_rule", "repair_hint", "failure_modes"))
        for record in search_function_memory(memory_query, limit=4)
    ]
    transfer_records = [
        _compact_record(record, ("label", "mutation_type", "from_pattern", "to_pattern", "parent_factor_id", "child_factor_id", "delta_score", "summary", "when_to_apply", "when_not_to_apply"))
        for record in search_transfer_memory(memory_query, limit=4)
    ]
    return _bounded_context(
        {
            "lineage_context": lineage_context,
            "specialist_memory": specialist_records,
            "function_memory": function_records,
            "transfer_memory": transfer_records,
        }
    )


def enhance_candidates(
    candidates: list[dict],
    feedback_records: list[dict] | None = None,
    *,
    max_new_candidates: int = 20,
    client: LLMClient | None = None,
    exploration_direction: str = "",
    lineage_states: dict[str, Any] | None = None,
) -> list[dict]:
    """Propose next-round candidates with the LLM factor mutation agent.

    The old rule-based mutation/crossover path has been removed. Without an
    LLM client this function returns no new candidates instead of making
    cosmetic formula edits.
    """
    if max_new_candidates <= 0 or client is None:
        return []

    plan = select_mutation_plan(candidates, feedback_records, lineage_states=lineage_states)
    if plan is None:
        return []
    effective_summary, ineffective_summary, metrics = _feedback_summary(plan.feedback_records)
    memory_context = _mutation_memory_context(plan, candidates, feedback_records)
    new_candidates = generate_factor_mutations(
        plan.parent_candidate,
        client,
        parent_logic=str(plan.parent_candidate.get("economic_rationale") or ""),
        evaluation_metrics=metrics,
        effective_summary=effective_summary,
        ineffective_summary=ineffective_summary,
        exploration_direction=exploration_direction,
        mutation_focus=plan.mutation_focus,
        agent_name=plan.agent_name,
        specialist_memory=memory_context["specialist_memory"],
        lineage_context=memory_context["lineage_context"],
        memory_context=memory_context,
        max_mutations=1,
    )
    write_specialist_mutation_memory(plan, new_candidates)
    return new_candidates[:max_new_candidates]


def propose_enhancements(feedback: dict) -> list[dict]:
    """Compatibility wrapper for callers that pass candidates and feedback together."""
    candidates = feedback.get("candidates", []) if isinstance(feedback, dict) else []
    feedback_records = feedback.get("feedback_records") or feedback.get("feedback") if isinstance(feedback, dict) else None
    return enhance_candidates(candidates, feedback_records)