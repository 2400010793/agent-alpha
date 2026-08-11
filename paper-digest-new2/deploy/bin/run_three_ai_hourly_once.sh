#!/usr/bin/env bash
set -euo pipefail
umask 000

PROJECT_ROOT="${PROJECT_ROOT:-/home/gaozh/my-paper-digest-new2}"
ENV_FILE="${ENV_FILE:-/home/gaozh/my-paper-digest-new/deploy/systemd/paper.env}"
PYTHON_BIN="${PYTHON_BIN:-${PROJECT_ROOT}/.venv/bin/python}"

cd "${PROJECT_ROOT}"
mkdir -p logs data/runtime

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

export PAPER_THREE_AI_HOURLY_MODEL="gpt-4o-mini"
export PAPER_READING_LLM_MODEL="gpt-4o-mini"
export PAPER_OPINION_LLM_MODEL="gpt-4o-mini"
# Use the OpenAI-compatible endpoint directly. Do not invoke copilot-p.
export PAPER_LLM_DIRECT_API="1"
export PAPER_READING_LLM_KEY_ENV="${PAPER_READING_LLM_KEY_ENV:-PAPER_LLM_API_KEY2}"
export PAPER_OPINION_LLM_KEY_ENV="${PAPER_OPINION_LLM_KEY_ENV:-PAPER_LLM_API_KEY}"

exec "${PYTHON_BIN}" -m src.pipeline.three_ai_hourly_once "$@"
