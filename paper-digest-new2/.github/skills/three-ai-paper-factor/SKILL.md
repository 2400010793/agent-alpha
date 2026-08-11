---
name: three-ai-paper-factor
description: "Use when: analyzing finance papers in my-paper-digest-new2 with the three-AI workflow: reading note extraction, HF factor generation, and faithfulness audit. Trigger phrases: reading_note_v1, paper_hf_factors, faithfulness_audit_v1, evidence_pack_v2, three AI paper pipeline."
---

# Three-AI Paper Factor Workflow

Use this workflow for `my-paper-digest-new2` paper analysis. The goal is to keep each LLM role narrow, auditable, and faithful to the paper evidence.

## Inputs

Primary inputs:

- `article_meta`: title, url, source id, source name, tags.
- `abstract`: article summary or abstract.
- `evidence_pack_v2`: structured evidence pack with section map, intro claims, formulas, variable definitions, methods, empirical snippets, and missing evidence.
- `evidence_pack`: legacy fallback evidence. Use only when `evidence_pack_v2` is missing a necessary detail.
- `context_providers`: mechanism taxonomy, proxy templates, local fields, allowed horizons.

## Stage 1: Reading Note LLM

The first LLM only reads the paper evidence. It must not generate HF factors.

Output schema: `reading_note_v1`.

Required content:

- `central_claim`: one concrete statement of the paper's main claim.
- `problem`: what question or market structure issue the paper studies.
- `method_logic`: how the method moves from assumptions to formulas to tests.
- `core_formulas`: formula, meaning, variable definitions, observability, and source anchor.
- `mechanism_chain`: ordered reasoning chain from phenomenon to model to result.
- `data_and_empirical_setup`: sample, frequency, assets, tests, missing fields.
- `key_results`: claims with short evidence and source anchors.
- `limitations`: identification, statistics, costs, sample, implementation, generality.
- `not_disclosed`: anything not present in the input, especially costs, t-stat, Sharpe, IC, OOS, capacity, or field availability.
- `faithfulness_constraints_for_next_llm`: constraints the factor generator must obey.

Rules:

- Prefer `evidence_pack_v2` over legacy evidence.
- Do not use conclusion, discussion, future work, references, or appendix as primary factor evidence.
- Do not fabricate undisclosed samples, statistics, costs, or implementation fields.
- Preserve source anchors whenever possible.

## Stage 2: HF Factor Generator LLM

The second LLM generates `paper_hf_factors` only from `reading_note_v1` and local context providers.

Output schema: existing `schema-v6` factor analysis.

Rules:

- Each factor must cite the reading note section it uses.
- If the paper does not directly define a tradable factor, mark it as mechanism-derived.
- Use `paper_hf_formula_plan` with declared templates or abstract operator families only.
- Do not output arbitrary Python as a trusted production formula.
- Put unavailable variables in `unobservable_variables` and `minimum_data_needed`.
- Use local fields only when they are actually supported by `local_capability_context`.

## Stage 3: Faithfulness Auditor LLM

The third LLM audits the generated factors against `reading_note_v1` and `evidence_pack_v2`.

Output schema: `faithfulness_audit_v1`.

Required checks:

- Formula changed meaning from the paper.
- Undisclosed sample, t-stat, Sharpe, IC, costs, OOS, or capacity was invented.
- Explanatory result was converted into predictive alpha without qualification.
- Unobservable variables were presented as local fields.
- Missing evidence constraints were violated.

Verdicts:

- `faithful`: supported by reading note and evidence anchors.
- `partially_faithful`: mechanism is plausible but some claims need revision.
- `unsupported`: factor is not grounded in the reading note.
- `hallucinated`: factor contains invented evidence or materially false claims.

Recommended actions:

- `accept`: publish/use.
- `rewrite`: revise factor or evidence text before use.
- `drop`: exclude from latest outputs and backtests.

## Operational Notes

Default script:

```bash
cd /mnt/lustre3/home/gaozh/my-paper-digest-new2
python3 -m src.llm.three_ai.pipeline --project-root .
```

Recommended models in the current Copilot CLI environment:

- Reading: `gpt-4.1` or `gpt-4o` for the longest observed context.
- Factor generation: `gpt-4.1` for stronger reasoning, or `gpt-4.1-mini` for cheaper tests.
- Audit: use a different key/model when available, e.g. key3 with `gpt-4.1` or `gpt-4o`.

Always save:

- `llm_reading_note`
- `llm_factor_generation_input`
- `llm_faithfulness_audit`
- `llm_input_evidence_pack_v2`
