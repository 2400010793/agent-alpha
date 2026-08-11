#!/bin/bash
#SBATCH --job-name=oa-85-sample
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=08:00:00
#SBATCH --output=logs/openalex-85-sample-%j.out

set -euo pipefail
cd "/mnt/lustre3/home/gaozh/paper graph"
mkdir -p logs data/raw/openalex data/processed/openalex_quant_sample
export PYTHONPATH="$PWD/.venv/lib/python3.9/site-packages:$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -c 'import sys, duckdb, paper_graph; print({"python": sys.version, "duckdb": duckdb.__version__, "paper_graph": paper_graph.__file__}, flush=True)'
python3 scripts/sync_openalex_snapshot.py \
  --entity works \
  --format parquet \
  --output-root data/raw/openalex \
  --sample-files 7
python3 scripts/extract_openalex_quant_candidates.py \
  --input-root data/raw/openalex/2026-06-26/parquet/works \
  --output-root data/processed/openalex_quant_sample \
  --min-year 2016 \
  --threads 4
