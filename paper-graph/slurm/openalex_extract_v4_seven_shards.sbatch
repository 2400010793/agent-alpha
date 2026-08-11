#!/bin/bash
#SBATCH --job-name=oa-extract-v4-7
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=08:00:00
#SBATCH --output=logs/openalex-extract-v4-seven-%j.out

set -euo pipefail
cd "/mnt/lustre3/home/gaozh/paper graph"
mkdir -p logs data/processed/openalex_quant_parquet_v4
export PYTHONPATH="$PWD/.venv/lib/python3.9/site-packages:$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -c 'import sys, duckdb, paper_graph; print({"python": sys.version, "duckdb": duckdb.__version__, "paper_graph": paper_graph.__file__}, flush=True)'
python3 scripts/extract_openalex_quant_candidates.py \
  --input-root data/raw/openalex/2026-06-26/parquet/works \
  --output-root data/processed/openalex_quant_parquet_v4 \
  --min-year 2016 \
  --threads 4 \
  --output-format both
python3 scripts/reconcile_openalex_extraction.py \
  --output-root data/processed/openalex_quant_parquet_v4 \
  --expected-input-files 7
