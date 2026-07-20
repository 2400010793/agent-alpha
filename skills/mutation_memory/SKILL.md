---
name: mutation_memory
description: Use when building or reading mutation memory_context for specialist factor mutation agents.
---

# mutation_memory

This skill defines the compact Cog-style memory used by Agent Alpha specialist mutation agents.

Rules:

- Memory is external and read-only for LLM mutation agents.
- LLMs must not claim access to memories that are not present in `memory_context`.
- LLMs must use memory as heuristic guidance, not as code to copy.
- Keep generated children distinct from ancestor prefixes in `lineage_context`.
- Prefer positive transfer examples and avoid BAD function patterns.
- If memory conflicts with field registry or ASL rules, field registry and ASL rules win.

## memory_context

`memory_context` is the only mutation memory block sent to specialist mutation agents.

```text
memory_context.lineage_context
memory_context.specialist_memory
memory_context.function_memory
memory_context.transfer_memory
memory_context.budget
```

## lineage_context

Purpose: prevent loops, ancestor reversion, and repeated empty mutations.

Contains:

- `root_factor_id`
- `parent_factor_id`
- `ancestor_count`
- `chain`: ordered ancestor records with `factor_id`, `prefix_expression`, `fields`, `windows`, `metrics`, `score`, and `delta_from_previous`

Use it to:

- Avoid returning to any ancestor `prefix_expression`.
- Prefer changes that previously improved score.
- Avoid changes that previously reduced score.

## specialist_memory

Purpose: memory private to the selected specialist agent.

Examples:

- EventDefinitionMutationAgent reads previous event-definition proposals.
- StateConditionMutationAgent reads previous state-condition proposals.
- NormalizationRobustnessMutationAgent reads previous normalization proposals.

Use it to avoid repeating the same proposal and to reuse concise principles.

## function_memory

Purpose: general memory about ASL ops, fields, windows, and function patterns.

Contains:

- `label`: GOOD, BAD, REVISE, or NEUTRAL
- `function_pattern`
- `asl_ops`
- `fields`
- `windows`
- `mechanism_tags`
- `condition`
- `summary`
- `avoid_rule`
- `repair_hint`
- `failure_modes`

Use it to answer:

- Which function/operator/field/window pattern is fragile?
- In what condition is it useful?
- What repair should be tried?

Do not reproduce BAD function patterns unless the mutation directly fixes the recorded failure.

## transfer_memory

Purpose: parent-to-child transition memory.

Contains:

- `mutation_type`
- `from_pattern`
- `to_pattern`
- `parent_factor_id`
- `child_factor_id`
- `parent_score`
- `child_score`
- `delta_score`
- `agent_name`
- `summary`
- `when_to_apply`
- `when_not_to_apply`

Use it to answer:

- Which mutation direction improved score?
- Which transition failed?
- When should this transfer be tried again?

Prefer transfer records with positive `delta_score` or GOOD label. Avoid BAD transfers and negative deltas.

## budget

`memory_context.budget` gives an approximate context limit.

- Default `max_chars`: 32000
- Approximate `max_tokens`: 8000

If memory is sparse, do not invent missing history. Use only the records provided.
