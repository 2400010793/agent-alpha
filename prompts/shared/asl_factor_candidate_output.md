# ASL FactorCandidate Output Format

Return strict JSON only. Do not return Markdown. Do not return Python code.

The root object must be:

```json
{
  "factor_candidates": []
}
```

Each `FactorCandidate` must contain:

```json
{
  "factor_id": "stable_snake_case_id",
  "name": "fac_eval_output_field_name",
  "prefix_expression": ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]],
  "expression": "safe_div((bidV1 - askV1), (bidV1 + askV1))",
  "fields": ["bidV1", "askV1"],
  "windows": [],
  "direction": "positive|negative|conditional|unknown",
  "source_signal_id": "",
  "source_reading_note_id": "",
  "mechanism_tags": ["order_book_pressure"],
  "economic_rationale": "One concise sentence tied to the signal evidence and mechanism."
}
```

ASL rules:

- Prefer `prefix_expression`; `expression` is only a readable compatibility view.
- Allowed ASL ops: `add`, `sub`, `mul`, `div`, `neg`, `safe_div`, `zscore`, `rolling_mean`, `rolling_std`, `rolling_sum`, `abs`, `clip`, `log1p`, `rank`.
- Window arguments must be positive integers and must use only current or historical observations.
- Keep one clear mechanism per candidate. Avoid decorative stacking such as `zscore(zscore(x))` or unrelated interactions.
- If the mechanism cannot be represented with allowed fields, return fewer candidates instead of inventing fields.

Forbidden output:

- No `def compute_factor`.
- No imports.
- No pandas/numpy code.
- No forward return labels in `fields`, `expression`, or `prefix_expression`.