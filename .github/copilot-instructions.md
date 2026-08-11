# Agent Alpha multi-project instructions

This repository is the signal, factor, experiment, evaluation and evolution layer of a three-project quantitative-research loop.

Before substantive work, read the shared handoff at `/home/gaozh/paper graph/docs/ai-handoff-three-project-loop.md`. Paper Graph owns canonical identity/OpenAlex/citation relations; `/home/gaozh/my-paper-digest-new2` owns source acquisition and full-text evidence; Agent Alpha consumes versioned evidence artifacts and returns evaluation/lineage/evidence-gap feedback.

Mandatory rules:

1. Long experiments, model/LLM runs and production fac-eval runs use Slurm; run cheap validation first.
2. Never kill or interrupt jobs/processes unless the user explicitly says `kill`.
3. Never change API-key, proxy or rate-limit policy without explicit approval.
4. Never discard existing uncommitted changes.
5. Do not submit new embedding-generation jobs.
6. Do not create a duplicate production paper crawler. Consume Paper Digest artifacts through a validated adapter.
7. Preserve canonical paper IDs, evidence IDs, reading-note IDs, signal/factor lineage, immutable experiment configs, metrics and evaluator reasons.
8. Run generated code only in a controlled environment with budgets and artifact manifests.
9. Before production fac-eval, verify the suspected tuple bug around `fac_eval_config_path` in `src/agent_alpha/search/experiment_runner.py` with a focused test.

The target return artifact is ResearchFeedbackV1: accepted/rejected factor outcomes, metrics, lineage, mechanism performance and evidence gaps for Paper Graph prioritization and Paper Digest follow-up.
