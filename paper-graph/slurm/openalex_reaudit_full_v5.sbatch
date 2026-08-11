#!/bin/bash
#SBATCH --job-name=oa-reaudit-full-v5
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=7-00:00:00
#SBATCH --output=logs/openalex-reaudit-full-v5-%j.out

set -euo pipefail
cd "/mnt/lustre3/home/gaozh/paper graph"
mkdir -p logs data/processed/openalex_quant_full_v5
export PYTHONPATH="$PWD/.venv/lib/python3.9/site-packages:$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
python3 scripts/reaudit_openalex_candidates_v5.py \
  --input-root data/processed/openalex_quant_full_v4/legacy_jsonl \
  --output-root data/processed/openalex_quant_full_v5
