#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

mode="${1:-dry-run}"
shift || true

if [[ -n "${PAPER_CLEAN_PYTHON:-}" ]]; then
  python_bin="$PAPER_CLEAN_PYTHON"
elif [[ -x "$PWD/.venv/bin/python" ]]; then
  python_bin="$PWD/.venv/bin/python"
else
  python_bin="$(command -v python3)"
fi
base_env=(
  env -i
  HOME="$HOME"
  USER="${USER:-gaozh}"
  LOGNAME="${LOGNAME:-${USER:-gaozh}}"
  SHELL="${SHELL:-/bin/bash}"
  PATH="$PWD/.venv/bin:/usr/local/bin:/usr/bin:/bin"
  LANG="${LANG:-C.UTF-8}"
  LC_ALL="${LC_ALL:-C.UTF-8}"
  PYTHONPATH="$PWD"
)

case "$mode" in
  probe)
    source_id="${1:-quantocracy_mashup}"
    shift || true
    exec "${base_env[@]}" "$python_bin" -m src.pipeline.probe_source_fetch --source-id "$source_id" "$@"
    ;;
  dry-run)
    exec "${base_env[@]}" \
      PAPER_ANALYSIS_MODE="${PAPER_ANALYSIS_MODE:-heuristic}" \
      PAPER_MAX_ITEMS_PER_SOURCE="${PAPER_MAX_ITEMS_PER_SOURCE:-5}" \
      "$python_bin" -m src.pipeline.daily_research_pipeline --project-root . --config config/sources.yaml --dry-run "$@"
    ;;
  run)
    exec "${base_env[@]}" \
      PAPER_ANALYSIS_MODE="${PAPER_ANALYSIS_MODE:-heuristic}" \
      "$python_bin" -m src.pipeline.daily_research_pipeline --project-root . --config config/sources.yaml "$@"
    ;;
  *)
    echo "usage: $0 probe [SOURCE_ID] [args...] | dry-run [args...] | run [args...]" >&2
    exit 2
    ;;
esac
