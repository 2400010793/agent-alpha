#!/usr/bin/env bash
set -euo pipefail
umask 000

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-python}"
PAPER_ROOT="${PAPER_ROOT:-${PROJECT_ROOT}}"
CONFIG_PATH="${CONFIG_PATH:-${PAPER_ROOT}/config/sources.yaml}"
DRY_RUN="${DRY_RUN:-0}"

CMD=(
  "${PYTHON_BIN}" -m src.pipeline.daily_research_pipeline
  --project-root "${PAPER_ROOT}"
  --config "${CONFIG_PATH}"
)

if [[ "${DRY_RUN}" == "1" ]]; then
  CMD+=(--dry-run)
fi

echo "[INFO] Running daily paper pipeline..."
echo "[INFO] ${CMD[*]}"
"${CMD[@]}"
