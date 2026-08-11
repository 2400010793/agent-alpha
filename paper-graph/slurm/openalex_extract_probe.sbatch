#!/bin/bash
#SBATCH --job-name=oa-extract-probe
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --output=logs/openalex-extract-probe-%j.out

set -euo pipefail
cd "/mnt/lustre3/home/gaozh/paper graph"
mkdir -p logs data/processed/openalex_quant_probe
export PYTHONPATH="$PWD/.venv/lib/python3.9/site-packages:$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -c 'import sys, duckdb, paper_graph; print({"python": sys.version, "duckdb": duckdb.__version__, "paper_graph": paper_graph.__file__}, flush=True)'
python3 scripts/extract_openalex_quant_candidates.py \
  --input-root data/raw/openalex/2026-06-26/parquet/works \
  --output-root data/processed/openalex_quant_probe \
  --min-year 2016 \
  --threads 2
