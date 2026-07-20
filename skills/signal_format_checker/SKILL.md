---
name: signal_format_checker
description: "Use when: checking or repairing LLM AlphaSignal or signal_mutation JSON before final output; validates required AlphaSignal fields, direction, allowed mechanism tags, allowed candidate fields, and no labels."
---

# signal_format_checker

Use this checklist before returning any `signal_mutations` JSON. Repair the JSON yourself before final output. Do not ask for another LLM call.

## Required Signal Shape

Every nested `signal` must contain:

- `signal_id`: non-empty stable string.
- `source_paper_id`: string, copied from parent if unchanged.
- `source_reading_note_id`: string, copied from parent if unchanged.
- `signal_name`: non-empty string.
- `market_intuition`: non-empty market mechanism explanation.
- `hypothesis`: non-empty testable hypothesis.
- `expected_direction`: `positive`, `negative`, `conditional`, or `unknown`.
- `hf_mechanism_tags`: list of allowed tags from `allowed_hf_mechanism_tags`.
- `candidate_fields`: list of allowed fields from `allowed_candidate_fields`.
- `evidence_ids`: list of strings.

## Mutation Record Shape

Every mutation must contain:

- `mutation_id`
- `mutation_type`, one of the allowed mutation types.
- `parent_signal_id`
- `parent_idea`
- `mutated_idea`
- `financial_reason`
- `expected_effect`
- `changed_components`
- `risk_note`
- `signal`

## Field And Tag Rules

- Use only provided `allowed_hf_mechanism_tags`; do not invent tags.
- Use only provided `allowed_candidate_fields`; do not invent fields.
- Never include label fields: `ret10s`, `ret30s`, `ret60s`, `ret120s`.
- Do not include unavailable fields such as `open`, `high`, `low`, `midP`, `wmidP`, `ret_mid`, or `trade_vol` unless they appear in `allowed_candidate_fields`.
- If a mutated idea requires unsupported fields, return fewer mutations instead of inventing fields.

## Content Rules

- Mutate signal ideas, not factor formulas.
- Do not output `FactorCandidate`.
- Do not output `prefix_expression`, `expression`, or Python code.
- Do not include `compute_factor`, imports, pandas/numpy code, or Markdown.
- Keep one clear market mechanism per mutated signal.
- If no meaningful signal mutation is possible, return `{ "signal_mutations": [] }`.

## Final Self-Check

Before final output, verify:

- Strict JSON only.
- Root object is `{ "signal_mutations": [...] }`.
- Every mutation has non-empty `mutated_idea` and `financial_reason`.
- Every nested signal passes the required signal shape.
- All tags and fields are copied from allowed lists.
- No forward-return labels are present.