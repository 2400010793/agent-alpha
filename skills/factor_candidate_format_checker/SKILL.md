---
name: factor_candidate_format_checker
description: "Use when: checking or repairing LLM FactorCandidate JSON before final output; validates ASL prefix_expression shape, fields/windows/expression consistency, forbidden fields, and no Python code."
---

# factor_candidate_format_checker

Use this checklist before returning any `FactorCandidate` or factor mutation JSON. Repair the JSON yourself before final output. Do not ask for another LLM call.

## Required Object Shape

Every candidate must be a JSON object with:

- `factor_id`: non-empty stable snake_case string.
- `name`: non-empty fac-eval output field name.
- `prefix_expression`: ASL list expression.
- `expression`: readable string matching `prefix_expression`.
- `fields`: list of input fields used by `prefix_expression`.
- `windows`: list of positive integer windows used by `prefix_expression`.
- `direction`: `positive`, `negative`, `conditional`, or `unknown`.
- `source_signal_id` and `source_reading_note_id`.
- `mechanism_tags`: list of mechanism strings.

`prefix_expression` is authoritative. `expression`, `fields`, and `windows` must be synchronized to it. If there is any conflict, repair the latter three to match the prefix.

## Allowed ASL Ops

Use only these exact lowercase op names:

```text
add
sub
mul
div
neg
safe_div
zscore
rolling_mean
rolling_std
rolling_sum
abs
clip
log1p
rank
```

Do not output aliases such as `mult`, `sum`, `SafeDiv`, `RollingMean`, `cond`, `ifelse`, `where`, `gt`, `maximum`, `minimum`, `ewm_mean`, `ewm_std`, `diff`, `corr`, or `beta` unless the prompt explicitly says those ops are now supported.

Do not output free-form expression strings that require unsupported renderer AST calls. The renderer rebuilds from `prefix_expression`, so the safe path is to make `prefix_expression` valid and derive everything else from it.

## Arity Rules

- Binary ops: `add`, `sub`, `mul`, `div`, `safe_div` take exactly 2 arguments.
- Unary ops: `neg`, `abs`, `log1p`, `rank` take exactly 1 argument.
- Window ops: `zscore`, `rolling_mean`, `rolling_std`, `rolling_sum` take exactly `[x, window]`; `window` must be a number, not a quoted string.
- `clip` takes exactly `[x, lower, upper]`; bounds must be numbers.

## Constants And Fields

- Numeric constants must be JSON numbers, e.g. `1`, `1e-6`, not strings like `"1"`.
- Never output placeholder identifiers such as `threshold_value`, `null`, `condition`, `x`, `y`, or `field` inside `prefix_expression`.
- `fields` must contain only actual allowed input or derived fields used in the prefix expression.
- Historical fac-idea aliases such as `open`, `high`, `low`, `midP`, `wmidP`, `ret_mid`, and `trade_vol` must not be used directly unless they are in the allowed field payload.
- Never include forward labels: `ret10s`, `ret30s`, `ret60s`, `ret120s`.
- Never include blocked fundamental/news/macro/industry/analyst/private fields.

## Self-Repair Examples

Repair aliases:

```json
["mult", "bidV1", "askV1"]
```

to:

```json
["mul", "bidV1", "askV1"]
```

Repair numeric strings:

```json
["safe_div", "volume", ["add", "close", "1"]]
```

to:

```json
["safe_div", "volume", ["add", "close", 1]]
```

Reject unsupported conditional placeholders instead of emitting invalid ASL:

```json
["cond", "threshold_value", "bidV1", "null"]
```

Return fewer candidates or an empty list if the idea requires unsupported ops.

## Final Self-Check

Before final output, verify:

- Strict JSON only; no Markdown.
- No Python code, no imports, no `compute_factor`.
- Every `prefix_expression` starts with an allowed op.
- No quoted numeric constants.
- `fields` exactly match fields used in `prefix_expression`.
- `windows` exactly match numeric windows used in `prefix_expression`.
- `expression` is a readable view of the same `prefix_expression`, not an independent formula.
- If you cannot express the mechanism with supported ASL and allowed fields, return fewer candidates instead of inventing unsupported names.
- A mutation candidate must not be only a simple reversal of its parent, such as `neg(parent)` or `mul(parent, -1)`. If direction repair is needed, use a nonlinear or state-dependent mechanism change.