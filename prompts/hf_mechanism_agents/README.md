# High-Frequency Mechanism Agent Prompts

These English prompts follow the CogAlpha prompt style but are rewritten for Agent Alpha's high-frequency setting.

Use these prompts after the reading gate passes:

```text
reading_note_v1
  -> AlphaSignal
  -> hf_mechanism_tags
  -> select one or more prompts in this directory
  -> FactorCandidate JSON with ASL prefix_expression
  -> controlled renderer
  -> fac-eval-compatible factor file
```

The current prompt set covers:

```text
order_book_pressure
depute_imbalance
trade_impact
price_volume_divergence
spread_liquidity
short_reversal
short_momentum
volatility_burst
book_shape
trading_rhythm
```

All prompts must include the shared high-frequency constraints:

```text
prompts/shared/hf_field_constraints.md
prompts/shared/hf_factor_requirements.md
prompts/shared/asl_factor_candidate_output.md
```

These mechanism prompts must not ask the LLM to write Python code. The LLM Implementer outputs FactorCandidate JSON only; `factor_file_renderer.py` and `fac_eval_renderer.py` are responsible for code generation.