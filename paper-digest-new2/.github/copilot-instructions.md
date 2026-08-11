# Paper Digest New2 multi-project instructions

This repository is the source-acquisition and full-text evidence layer of a three-project quantitative-research loop.

Before substantive work, read the shared handoff at `/home/gaozh/paper graph/docs/ai-handoff-three-project-loop.md`. Paper Graph owns canonical identity, OpenAlex discovery and citation relations; this repository owns arXiv/PDF/TeX/HTML acquisition, document chunks, evidence packs and evidence-backed reading artifacts; `/home/gaozh/agent_alpha` owns signal/factor experiments and evaluation.

Mandatory rules:

1. Long source collection, full-text parsing and LLM runs use Slurm; validate configuration and startup on a cheap probe first.
2. Never kill/restart existing services, jobs or background processes unless the user explicitly says `kill`.
3. Never change API-key, proxy or rate-limit policy without explicit approval.
4. Never discard existing uncommitted changes or overwrite stable archives/runtime state.
5. Preserve canonical paper IDs, exact arXiv/DOI/OpenAlex identities, content versions, section/page/TeX locations and stable evidence IDs.
6. Export versioned artifacts to Agent Alpha; do not couple by title matching.
7. Do not generate new embeddings.
8. The exact 85-term source vocabulary in `config/sources.yaml` is the current retrieval vocabulary used by Paper Graph.

The required integration is Digest evidence_pack_v2/three-AI output -> shared ResearchArtifactEnvelopeV1 -> Agent Alpha, with evaluation/evidence-gap feedback returned upstream.
