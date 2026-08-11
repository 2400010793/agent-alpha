#!/bin/bash
#SBATCH --job-name=oa-api-anon
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --output=logs/openalex-api-anonymous-%j.out

set -euo pipefail
cd "/mnt/lustre3/home/gaozh/paper graph"
mkdir -p logs data/processed/openalex_api_quant_pilot_v1

# Deliberately hide any inherited key: this job uses only the shared anonymous
# daily allowance and stops safely when OpenAlex reports that it is exhausted.
unset OPENALEX_API_KEY
export PYTHONPATH="$PWD/.venv/lib/python3.9/site-packages:$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
python3 scripts/fetch_openalex_api_candidates.py \
  --output-root data/processed/openalex_api_quant_pilot_v1 \
  --filter-profile v5 \
  --max-pages 80 \
  --max-cost-usd 0.08 \
  --delay 1
