#!/bin/bash
#SBATCH --job-name=oa-snapshot-4x4
#SBATCH --partition=cpu
#SBATCH --nodes=4
#SBATCH --ntasks=4
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=7-00:00:00
#SBATCH --output=logs/openalex-snapshot-sharded-%j.out

set -euo pipefail
cd "/mnt/lustre3/home/gaozh/paper graph"
mkdir -p logs data/raw/openalex
srun --kill-on-bad-exit=1 --label bash -c '
  python3 scripts/sync_openalex_snapshot.py \
    --entity works \
    --format parquet \
    --output-root data/raw/openalex \
    --manifest data/raw/openalex/2026-06-26/parquet/works/manifest.json \
    --shard-count 4 \
    --shard-index "${SLURM_PROCID}" \
    --workers 4
'
