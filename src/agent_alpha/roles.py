from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentRole:
    name: str
    responsibility: str
    input_schema: str
    output_schema: str


IDEA_PERSON = AgentRole(
    name="The Idea Person",
    responsibility="Read structured paper memory and propose high-frequency alpha signals.",
    input_schema="ReadingNote + evidence refs + field whitelist + memory snippets",
    output_schema="AlphaSignal",
)

IMPLEMENTER = AgentRole(
    name="The Implementer",
    responsibility="Convert high-frequency alpha signals into fac-eval compatible factor candidates.",
    input_schema="AlphaSignal + allowed fields + HF taxonomy + GOOD/BAD memory",
    output_schema="FactorCandidate + factor file skeleton",
)

EVALUATOR = AgentRole(
    name="The Evaluator",
    responsibility="Evaluate statistics, implementation safety, and economic logic before library admission.",
    input_schema="FactorCandidate + fac-eval metrics + source evidence",
    output_schema="ResearchReviewRecord",
)


THREE_ROLES = (IDEA_PERSON, IMPLEMENTER, EVALUATOR)