from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_alpha.memory.function_memory import DEFAULT_FUNCTION_MEMORY_PATH, append_function_memory
from agent_alpha.memory.mutation_arm_memory import DEFAULT_MUTATION_ARM_MEMORY_PATH, append_mutation_arm_event
from agent_alpha.memory.specialist_memory import DEFAULT_SPECIALIST_MEMORY_DIR, append_specialist_memory
from agent_alpha.memory.transfer_memory import DEFAULT_TRANSFER_MEMORY_PATH, append_transfer_memory
from agent_alpha.llm.client import LLMClient
from agent_alpha.llm.prompt_runner import load_prompt
from agent_alpha.search.mutation_controller import MutationPlan


def _factor_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("factor_id") or candidate.get("name") or "")


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _prefix_pattern(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if value is not None else ""


def _asl_ops(value: Any) -> list[str]:
    ops: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, list) and node:
            if isinstance(node[0], str):
                ops.append(node[0])
            for item in node[1:]:
                walk(item)
        elif isinstance(node, dict):
            op = node.get("op")
            if isinstance(op, str):
                ops.append(op)
            for item in _as_list(node.get("args")):
                walk(item)

    walk(value)
    return list(dict.fromkeys(ops))


def _label_from_review(review: dict[str, Any] | None) -> str:
    if not review:
        return "NEUTRAL"
    decision = str(review.get("decision") or "").casefold()
    if decision == "accept":
        return "GOOD"
    if decision == "reject":
        return "BAD"
    if decision == "revise":
        return "REVISE"
    return str(review.get("label") or "NEUTRAL").upper()


def _score(review: dict[str, Any] | None) -> float | None:
    metrics = review.get("metrics") if isinstance(review, dict) and isinstance(review.get("metrics"), dict) else {}
    for key in ("daily_rankic", "global_rankic", "rankic", "daily_ic", "global_ic"):
        try:
            return abs(float(metrics[key])) if key in metrics else None
        except (TypeError, ValueError):
            return None
    return None


def _short_text(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _valid_label(value: Any) -> str:
    label = str(value or "").upper()
    return label if label in {"GOOD", "BAD", "REVISE", "NEUTRAL"} else "NEUTRAL"


def _clean_function_memory(records: list[Any], *, limit: int = 1) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        summary = _short_text(record.get("summary"))
        if not summary:
            continue
        out.append(
            {
                "label": _valid_label(record.get("label")),
                "function_pattern": _short_text(record.get("function_pattern"), 120),
                "summary": summary,
                "avoid_rule": _short_text(record.get("avoid_rule"), 160),
                "repair_hint": _short_text(record.get("repair_hint"), 160),
            }
        )
        if len(out) >= limit:
            break
    return out


def _clean_transfer_memory(records: list[Any], *, limit: int = 2) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        summary = _short_text(record.get("summary"))
        mutation_type = _short_text(record.get("mutation_type"), 80)
        if not summary or not mutation_type:
            continue
        out.append(
            {
                "label": _valid_label(record.get("label")),
                "mutation_type": mutation_type,
                "summary": summary,
                "when_to_apply": _short_text(record.get("when_to_apply"), 160),
                "when_not_to_apply": _short_text(record.get("when_not_to_apply"), 160),
            }
        )
        if len(out) >= limit:
            break
    return out


@dataclass(frozen=True)
class MemorySummaryPaths:
    specialist_root: str | Path = DEFAULT_SPECIALIST_MEMORY_DIR
    function_memory_path: str | Path = DEFAULT_FUNCTION_MEMORY_PATH
    transfer_memory_path: str | Path = DEFAULT_TRANSFER_MEMORY_PATH
    mutation_arm_memory_path: str | Path = DEFAULT_MUTATION_ARM_MEMORY_PATH


class MemorySummaryAgent:
    """Rule-based Cog-style memory distiller for mutation outcomes.

    This agent does not call an LLM. It writes compact memories consumed by
    future specialist mutation agents and MCP memory search tools.
    """

    def __init__(self, paths: MemorySummaryPaths | None = None) -> None:
        self.paths = paths or MemorySummaryPaths()

    def summarize_specialist(self, plan: MutationPlan, child_candidate: dict[str, Any], child_review: dict[str, Any] | None = None) -> dict[str, Any]:
        parent = plan.parent_candidate
        label = _label_from_review(child_review)
        return {
            "label": label,
            "memory_type": "mutation_proposal",
            "mutation_focus": plan.mutation_focus,
            "parent_factor_id": _factor_id(parent),
            "child_factor_id": _factor_id(child_candidate),
            "summary": str(child_candidate.get("mutated_idea") or child_candidate.get("economic_rationale") or plan.reason),
            "reason": plan.reason,
            "mechanism_tags": list(child_candidate.get("mechanism_tags") or parent.get("mechanism_tags") or []),
            "fields": list(child_candidate.get("fields") or []),
            "prefix_expression": child_candidate.get("prefix_expression"),
        }

    def summarize_function(self, plan: MutationPlan, child_candidate: dict[str, Any], child_review: dict[str, Any] | None = None) -> dict[str, Any]:
        prefix = child_candidate.get("prefix_expression")
        label = _label_from_review(child_review)
        failure_modes = [str(item) for item in _as_list((child_review or {}).get("failure_modes"))]
        return {
            "label": label,
            "function_pattern": _prefix_pattern(prefix),
            "asl_ops": _asl_ops(prefix),
            "fields": list(child_candidate.get("fields") or []),
            "windows": list(child_candidate.get("windows") or []),
            "mechanism_tags": list(child_candidate.get("mechanism_tags") or []),
            "condition": plan.mutation_focus,
            "summary": str(child_candidate.get("economic_rationale") or child_candidate.get("mutated_idea") or plan.reason),
            "avoid_rule": str((child_review or {}).get("avoid_rule") or "") if label == "BAD" else "",
            "repair_hint": str((child_review or {}).get("repair_hint") or "") if label in {"BAD", "REVISE"} else "",
            "failure_modes": failure_modes,
            "source_factor_ids": [_factor_id(plan.parent_candidate), _factor_id(child_candidate)],
        }

    def summarize_transfer(self, plan: MutationPlan, child_candidate: dict[str, Any], child_review: dict[str, Any] | None = None, parent_review: dict[str, Any] | None = None) -> dict[str, Any]:
        parent_score = _score(parent_review)
        child_score = _score(child_review)
        delta_score = child_score - parent_score if parent_score is not None and child_score is not None else None
        label = _label_from_review(child_review)
        return {
            "label": label,
            "mutation_type": plan.mutation_focus,
            "from_pattern": _prefix_pattern(plan.parent_candidate.get("prefix_expression")),
            "to_pattern": _prefix_pattern(child_candidate.get("prefix_expression")),
            "parent_factor_id": _factor_id(plan.parent_candidate),
            "child_factor_id": _factor_id(child_candidate),
            "parent_score": parent_score,
            "child_score": child_score,
            "delta_score": delta_score,
            "mechanism_tags": list(child_candidate.get("mechanism_tags") or plan.parent_candidate.get("mechanism_tags") or []),
            "agent_name": plan.agent_name,
            "summary": str(child_candidate.get("mutated_idea") or child_candidate.get("economic_rationale") or plan.reason),
            "when_to_apply": plan.reason if label in {"GOOD", "NEUTRAL"} else "",
            "when_not_to_apply": plan.reason if label == "BAD" else "",
        }

    def write_mutation_memories(
        self,
        plan: MutationPlan,
        child_candidate: dict[str, Any],
        *,
        child_review: dict[str, Any] | None = None,
        parent_review: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        specialist = append_specialist_memory(plan.agent_name, self.summarize_specialist(plan, child_candidate, child_review), root=self.paths.specialist_root)
        function = append_function_memory(self.summarize_function(plan, child_candidate, child_review), path=self.paths.function_memory_path)
        transfer = append_transfer_memory(self.summarize_transfer(plan, child_candidate, child_review, parent_review), path=self.paths.transfer_memory_path)
        records = {"specialist": specialist, "function": function, "transfer": transfer}
        if child_review is not None:
            parent_score = _score(parent_review)
            child_score = _score(child_review)
            if parent_score is not None and child_score is not None:
                reward = child_score - parent_score
            elif child_score is not None:
                reward = child_score
            else:
                reward = 0.0
            label = _label_from_review(child_review)
            lineage_id = str(plan.parent_candidate.get("lineage_id") or plan.parent_candidate.get("factor_id") or plan.parent_candidate.get("name") or "unknown_lineage")
            records["mutation_arm"] = append_mutation_arm_event(
                {
                    "lineage_id": lineage_id,
                    "mutation_focus": plan.mutation_focus,
                    "agent_name": plan.agent_name,
                    "parent_factor_id": _factor_id(plan.parent_candidate),
                    "child_factor_id": _factor_id(child_candidate),
                    "label": label,
                    "reward": reward,
                    "success": label == "GOOD" and reward > 0,
                    "summary": str(child_candidate.get("mutated_idea") or child_candidate.get("economic_rationale") or plan.reason),
                },
                path=self.paths.mutation_arm_memory_path,
            )
        return records

    def write_llm_summaries(self, records: list[dict[str, Any]], client: LLMClient, *, max_records: int = 12, max_function_memory: int = 1, max_transfer_memory: int = 2) -> dict[str, list[dict[str, Any]]]:
        summary = self.summarize_with_llm(records, client, max_records=max_records, max_function_memory=max_function_memory, max_transfer_memory=max_transfer_memory)
        written_function = [append_function_memory(record, path=self.paths.function_memory_path) for record in summary.get("function_memory", []) if isinstance(record, dict)]
        written_transfer = [append_transfer_memory(record, path=self.paths.transfer_memory_path) for record in summary.get("transfer_memory", []) if isinstance(record, dict)]
        return {"function_memory": written_function, "transfer_memory": written_transfer}

    def summarize_with_llm(self, records: list[dict[str, Any]], client: LLMClient, *, max_records: int = 12, max_function_memory: int = 1, max_transfer_memory: int = 2) -> dict[str, Any]:
        """Optionally distill batches into very short Cog-style memories.

        This is not used in the default mutation path; callers can run it once
        per generation or after N samples to keep memory concise.
        """
        payload = {
            "records": records[:max_records],
            "max_summary_chars": 180,
            "max_function_memory": max_function_memory,
            "max_transfer_memory": max_transfer_memory,
            "style": "Observation -> Cause -> Fix",
        }
        try:
            response = client.complete_json(
                [
                    {"role": "system", "content": load_prompt("prompts/thinking_evolution/memory_summary_v1_system.md")},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ]
            )
        except RuntimeError:
            return {"function_memory": [], "transfer_memory": []}
        return {
            "function_memory": _clean_function_memory(response.get("function_memory", []) if isinstance(response.get("function_memory"), list) else [], limit=max_function_memory),
            "transfer_memory": _clean_transfer_memory(response.get("transfer_memory", []) if isinstance(response.get("transfer_memory"), list) else [], limit=max_transfer_memory),
        }


__all__ = ["MemorySummaryAgent", "MemorySummaryPaths"]
