---
name: signal_to_factor
description: Convert high-frequency alpha signals into validated FactorCandidate objects. Rendering code is handled by the controlled fac-eval renderer.
---

# signal_to_factor

Rules:

- Use only fields allowed by `configs/field_registry.yaml`.
- Never use forward label fields such as `ret10s`, `ret30s`, `ret60s`, or `ret120s` inside the factor expression.
- Do not output arbitrary Python code.
- Do not output `compute_factor` directly.
- Output only a `FactorCandidate` object with `factor_id`, `name`, `prefix_expression`, `expression`, `fields`, `windows`, `direction`, `source_signal_id`, `source_reading_note_id`, and `mechanism_tags`.
- Prefer `prefix_expression` in Agent Alpha Structured Language (ASL), because it is easier to validate and render safely.
- Also include a readable `expression` string as a compatibility view of the same logic.
- Allowed ASL ops are: `add`, `sub`, `mul`, `div`, `neg`, `safe_div`, `zscore`, `rolling_mean`, `rolling_std`, `rolling_sum`, `abs`, `clip`, `log1p`, `log`, `tanh`, `sign`, `rank`, `max`, `min`, `gt`, `lt`, `ge`, `le`, `eq`, `neq`, `and`, `or`, `where`, `diff`, `shift`, `pct_change`, `ewm_mean`, `ewm_std`, `rolling_min`, `rolling_max`, `rolling_median`, `rolling_rank`, `rolling_count`, `rolling_corr`, `rolling_cov`, `rolling_beta`, `div_mean`, `div_std`, and `vol_scale`.
- Example ASL: `["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]]`.
- The expression string, when present, must be a readable view derived from `prefix_expression`. It is not authoritative; the controlled renderer rebuilds from `prefix_expression`.
- The controlled renderer is responsible for producing the fac-eval file with module variable `fields` and function `compute_factor(code, date, df)`.

Pipeline boundary:

```text
FactorCandidate
	-> expression_validator
	-> factor_file_renderer
	-> py_compile
	-> fac_eval_adapter
```