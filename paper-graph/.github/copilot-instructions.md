# Paper Graph multi-project instructions

Before doing substantive work, read `docs/ai-handoff-three-project-loop.md`, then the relevant canonical plan:

- `docs/global-implementation-plan.md`
- `docs/openalex-85-keyword-seed-plan.md`
- `docs/scinet-adaptation-plan.md`

This repository is the orchestration and canonical identity/relationship layer of a three-project loop with `/home/gaozh/my-paper-digest-new2` and `/home/gaozh/agent_alpha`.

Mandatory rules:

1. Long downloads, scans, graph builds, full-text/LLM work and experiments use Slurm; probe first.
2. Never kill or interrupt jobs/processes unless the user explicitly says `kill`.
3. Never submit new embedding-generation jobs; reuse existing embeddings or stay citation-only.
4. Never change API-key, proxy or rate-limit policy without explicit approval.
5. Never discard existing uncommitted changes.
6. Preserve retrieval/audit/seed separation, exact identities, relation semantics, evidence provenance and run manifests.
7. Check `squeue` and logs before resubmitting OpenAlex work. The handoff records the last verified sample job and snapshot state.
8. Integrate the three repositories through versioned artifact contracts, not title matching, duplicated crawlers or large-directory copying.

The target flow is Paper Graph discovery/identity/relations -> Paper Digest full-text evidence -> Agent Alpha signals/factors/evaluation -> feedback to Graph and Digest.
