#!/bin/bash
#SBATCH --job-name=oa-snapshot
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=16
#SBATCH --mem=16G
#SBATCH --time=7-00:00:00
#SBATCH --output=logs/openalex-snapshot-%j.out

set -euo pipefail
cd "/mnt/lustre3/home/gaozh/paper graph"
mkdir -p logs data/raw/openalex
python3 scripts/sync_openalex_snapshot.py \
  --entity works \
  --format parquet \
  --output-root data/raw/openalex \
  --manifest data/raw/openalex/2026-06-26/parquet/works/manifest.json \
  --workers 16
