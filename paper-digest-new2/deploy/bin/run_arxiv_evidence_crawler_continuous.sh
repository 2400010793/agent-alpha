#!/usr/bin/env bash
set -euo pipefail
umask 000

PROJECT_ROOT="${PROJECT_ROOT:-/home/gaozh/my-paper-digest-new2}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SLEEP_SEC="${PAPER_ARXIV_CRAWLER_SLEEP_SEC:-120}"
EMPTY_SLEEP_SEC="${PAPER_ARXIV_CRAWLER_EMPTY_SLEEP_SEC:-900}"

cd "${PROJECT_ROOT}"
mkdir -p logs data/runtime

exec "${PYTHON_BIN}" -m src.pipeline.arxiv_evidence_crawler --forever --sleep-sec "${SLEEP_SEC}" --empty-sleep-sec "${EMPTY_SLEEP_SEC}" "$@"