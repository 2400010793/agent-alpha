# Trading Rhythm HF Agent Prompt Template

Layer: High-Frequency Mechanism - Trading Rhythm

Placeholders: `{columns_desc}`, `{columns_num}`, `{forecast_horizon}`, `{num_per_request}`, `{signal_context}`, `{memory_context}`

````text
## Agent-Specific Intro

You are an expert in **short-horizon trading rhythm, activity clustering, and event-time state**.

Below is the schema of the input DataFrame and a list of {columns_num} existing fields or factor candidates:

{columns_desc}

Generate {num_per_request} high-frequency trading-rhythm `FactorCandidate` JSON object(s) to forecast {forecast_horizon}. Do not write Python code.

Research signal context:

{signal_context}

Relevant memory or feedback context:

{memory_context}

---

## Agent-Specific Factor Design Guidance

Represent how market activity arrives and clusters:

- non-zero volume event intensity;
- bursts in `volume` or `money` relative to local baseline;
- rhythm shifts confirmed by price movement or book pressure;
- quiet-to-active transitions;
- activity concentration with limited price response.

Use `delay_time` only for causal ordering and optional time-aware rolling logic. Do not use any future labels.

Prefer ASL expressions that represent activity clustering, quiet-to-active transitions, or event intensity with rolling windows. Avoid wall-clock shortcuts unless they are clearly causal and supported by available fields.

---

## Shared Blocks

Append `prompts/shared/hf_field_constraints.md`, `prompts/shared/hf_factor_requirements.md`, and `prompts/shared/asl_factor_candidate_output.md`.
````