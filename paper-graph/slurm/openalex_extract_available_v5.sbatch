#!/bin/bash
#SBATCH --job-name=oa-extract-now-v5
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=08:00:00
#SBATCH --output=logs/openalex-extract-available-v5-%j.out

set -euo pipefail
cd "/mnt/lustre3/home/gaozh/paper graph"
mkdir -p logs data/processed/openalex_quant_available_v5
export PYTHONPATH="$PWD/.venv/lib/python3.9/site-packages:$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

# The extractor snapshots the list of completed *.parquet files at startup, so
# concurrent snapshot downloads can continue writing *.partial files safely.
python3 scripts/extract_openalex_quant_candidates.py \
  --input-root data/raw/openalex/2026-06-26/parquet/works \
  --output-root data/processed/openalex_quant_available_v5 \
  --min-year 2016 \
  --threads 4 \
  --filter-profile v5 \
  --output-format parquet
