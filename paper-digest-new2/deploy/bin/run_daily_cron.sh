#!/usr/bin/env bash
set -euo pipefail
umask 000

PROJECT_ROOT="${PROJECT_ROOT:-/data/share/paper-digest}"
ENV_FILE="${ENV_FILE:-${PROJECT_ROOT}/deploy/systemd/paper.env}"
LOG_FILE="${LOG_FILE:-${PROJECT_ROOT}/logs/cron_daily.log}"

cd "${PROJECT_ROOT}"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

export PYTHON_BIN="${PYTHON_BIN:-/home/zhangq/.conda/envs/zq_dev/bin/python}"
export PAPER_ROOT="${PAPER_ROOT:-${PROJECT_ROOT}}"

mkdir -p "$(dirname "${LOG_FILE}")"

{
  echo "[INFO] cron run started at $(date '+%Y-%m-%d %H:%M:%S %z')"
  bash "${PROJECT_ROOT}/deploy/bin/run_daily.sh"
  echo "[INFO] cron run finished at $(date '+%Y-%m-%d %H:%M:%S %z')"
} >>"${LOG_FILE}" 2>&1
