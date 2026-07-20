# Environment Setup

Agent Alpha calls LLM models through API keys stored in environment variables.

Do not commit real API keys to this repository.

## Parser Dependencies

The parser-to-reader flow normalizes PDF, arXiv LaTeX source, HTML, Markdown, and text into the same `ParsedPaper` and `EvidenceChunk` interface before any reading step.

- PDF parsing uses `pypdf` and is listed in `pyproject.toml` dependencies.
- arXiv LaTeX source parsing uses Python standard-library `tarfile` plus lightweight TeX text extraction; no extra LaTeX package is required for the first version.
- HTML, Markdown, and text parsing use the Python standard library.

Install project dependencies before running local ingestion:

```bash
pip install -e .
```

## Recommended Variables

```bash
export AGENT_ALPHA_LLM_BASE_URL="https://models.github.ai/inference"
export AGENT_ALPHA_LLM_API_KEY="<your-api-key>"
export AGENT_ALPHA_LLM_MODEL="openai/gpt-4o"
export AGENT_ALPHA_LLM_TIMEOUT_SEC="300"
export AGENT_ALPHA_LLM_RETRIES="2"
export AGENT_ALPHA_LLM_MIN_INTERVAL_SEC="10"
```

## Compatibility Variables

The loader also accepts existing paper-digest style names:

```bash
export PAPER_LLM_BASE_URL="https://models.github.ai/inference"
export PAPER_LLM_API_KEY1="<your-api-key-1>"
export PAPER_LLM_API_KEY2="<your-api-key-2>"
export PAPER_LLM_API_KEY3="<your-api-key-3>"
export PAPER_LLM_MODEL="openai/gpt-4o"
export PAPER_LLM_TIMEOUT_SEC="300"
export PAPER_LLM_RETRIES="2"
export PAPER_LLM_MIN_INTERVAL_SEC="10"
```

`AGENT_ALPHA_*` variables take priority when both naming schemes are present.

## Security Rules

- API keys are read only from environment variables.
- API keys must not appear in YAML files, README, logs, tests, or audit output.
- LLM audit logs should record the env var name or key slot, not the secret value.