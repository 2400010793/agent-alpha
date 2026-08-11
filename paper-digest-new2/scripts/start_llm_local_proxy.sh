#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROXY_SCRIPT="/home/gaozh/my-paper-digest-new/scripts/llm_local_proxy.py"
PYTHON_BIN="${PYTHON_BIN:-${ROOT}/.venv/bin/python}"

export PAPER_PROXY_HOST="${PAPER_PROXY_HOST:-127.0.0.1}"
export PAPER_PROXY_PORT="${PAPER_PROXY_PORT:-8787}"
export PAPER_PROXY_UPSTREAM_URL="${PAPER_PROXY_UPSTREAM_URL:-https://models.github.ai/inference}"
export PAPER_PROXY_LOG="${PAPER_PROXY_LOG:-${ROOT}/logs/llm_proxy_traffic.jsonl}"
export PAPER_PROXY_AIC_LOG="${PAPER_PROXY_AIC_LOG:-${ROOT}/logs/llm_aic_calls.jsonl}"

exec "${PYTHON_BIN}" "${PROXY_SCRIPT}"
