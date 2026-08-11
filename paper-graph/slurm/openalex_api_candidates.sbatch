#!/bin/bash
#SBATCH --job-name=oa-api-candidates
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=1-00:00:00
#SBATCH --output=logs/openalex-api-candidates-%j.out

set -euo pipefail
cd "/mnt/lustre3/home/gaozh/paper graph"
mkdir -p logs data/processed/openalex_api_quant_pilot_v1

# Prefer an exported variable.  For unattended jobs, keep the key outside the
# repository in a mode-0600 file containing only the key itself.
if [[ -z "${OPENALEX_API_KEY:-}" ]]; then
  openalex_key_file="${OPENALEX_API_KEY_FILE:-${HOME}/.config/paper-graph/openalex_api_key}"
  if [[ -r "$openalex_key_file" ]]; then
    IFS= read -r OPENALEX_API_KEY < "$openalex_key_file" || [[ -n "$OPENALEX_API_KEY" ]]
    export OPENALEX_API_KEY
  fi
fi
if [[ -z "${OPENALEX_API_KEY:-}" ]]; then
  echo "OPENALEX_API_KEY is not configured; see scripts/README.md" >&2
  exit 2
fi

export PYTHONPATH="$PWD/.venv/lib/python3.9/site-packages:$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
python3 scripts/fetch_openalex_api_candidates.py \
  --output-root data/processed/openalex_api_quant_pilot_v1 \
  --filter-profile v5 \
  --max-pages 250 \
  --max-cost-usd 0.25 \
  --delay 1
