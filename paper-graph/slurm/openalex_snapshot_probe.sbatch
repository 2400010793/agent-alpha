#!/bin/bash
#SBATCH --job-name=oa-snapshot-probe
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:20:00
#SBATCH --output=logs/openalex-snapshot-probe-%j.out

set -euo pipefail
cd "/mnt/lustre3/home/gaozh/paper graph"
mkdir -p logs data/raw/openalex
python3 scripts/sync_openalex_snapshot.py \
  --entity works \
  --format parquet \
  --output-root data/raw/openalex \
  --max-files 1