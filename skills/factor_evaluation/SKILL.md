---
name: factor_evaluation
description: Review fac-eval results and decide whether a high-frequency factor should be accepted, revised, or rejected.
---

# factor_evaluation

Rules:

- Use fac-eval metrics such as IC, RankIC, ICIR, qspread, finite ratio, and zero ratio.
- Treat `fac-eval-demo` as the owner of calculation and metric generation.
- Agent Alpha only reads fac-eval result payloads and makes research-quality decisions.
- Check implementation quality before economic logic.
- Reject factors with forbidden fields, forward label leakage, or missing rationale.
- Output a `ResearchReviewRecord` with decision `accept`, `revise`, or `reject`.

Standard fac-eval interface:

```text
rendered_factor_file.py
	declares fields = ["factor_name"]
	defines compute_factor(code, date, df)

fac_eval_config.yaml
	includes factor_files:
		- path: rendered_factor_file.py
			func: compute_factor
```