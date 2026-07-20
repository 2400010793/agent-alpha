from __future__ import annotations

from typing import Any

from agent_alpha.memory.memory_summary_agent import MemorySummaryAgent
from agent_alpha.search.mutation_controller import MutationPlan


def summarize_mutation_proposal(plan: MutationPlan, child_candidate: dict[str, Any]) -> dict[str, Any]:
    return MemorySummaryAgent().summarize_specialist(plan, child_candidate)


def write_specialist_mutation_memory(plan: MutationPlan, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    agent = MemorySummaryAgent()
    for child in children:
        records.append(agent.write_mutation_memories(plan, child)["specialist"])
    return records


__all__ = ["summarize_mutation_proposal", "write_specialist_mutation_memory"]