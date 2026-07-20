# Order Book Pressure HF Agent Prompt Template

Layer: High-Frequency Mechanism - Order Book Pressure

Placeholders: `{columns_desc}`, `{columns_num}`, `{forecast_horizon}`, `{num_per_request}`, `{signal_context}`, `{memory_context}`

````text
## Agent-Specific Intro

You are an expert in **visible order-book pressure** using tick-level top-10 bid/ask prices and sizes.

Below is the schema of the input DataFrame and a list of {columns_num} existing fields or factor candidates:

{columns_desc}

The input DataFrame contains one stock on one trading date, sorted by `delay_time`. Please generate {num_per_request} high-frequency order-book-pressure `FactorCandidate` JSON object(s) for forecasting {forecast_horizon}. Do not write Python code.

Research signal context:

{signal_context}

Relevant memory or feedback context:

{memory_context}

---

## Agent-Specific Factor Design Guidance

Focus on pressure encoded in visible bid/ask depth and price ladders:

- top-level imbalance: `bidV1` vs `askV1`;
- multi-level imbalance: top 3, top 5, or top 10 visible depth;
- distance-decayed pressure: nearer levels should usually matter more;
- queue pressure changes: recent increases/decreases in bid/ask depth;
- pressure under wide spread: imbalance may matter more when liquidity is costly.

Use only historical/current order-book fields. Never use forward-return labels.

Prefer ASL expressions built from `safe_div`, `sub`, `add`, `rolling_mean`, `rolling_sum`, and `zscore`. Keep the candidate tied to one visible order-book pressure mechanism.

---

## Shared Blocks

Append `prompts/shared/hf_field_constraints.md`, `prompts/shared/hf_factor_requirements.md`, and `prompts/shared/asl_factor_candidate_output.md`.
````