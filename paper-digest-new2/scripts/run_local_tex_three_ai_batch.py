#!/usr/bin/env python3
"""Run downloaded TeX evidence through reading and generic research analysis."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "bin" / "python"


def read_jsonl(path: Path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
            except json.JSONDecodeError:
                pass
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-archive", type=Path, default=ROOT / "data/arxiv_tex_evidence_archive.jsonl")
    parser.add_argument("--analysis-archive", type=Path, default=ROOT / "data/arxiv_tex_three_ai_analysis.jsonl")
    parser.add_argument("--copilot-bin", default="/home/gaozh/.local/bin/copilot-p")
    parser.add_argument("--model", default="gpt-5-mini")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout-sec", type=int, default=900)
    args = parser.parse_args()
    evidence = read_jsonl(args.evidence_archive)
    completed = {str(row.get("arxiv_id")) for row in read_jsonl(args.analysis_archive) if row.get("status") == "ok"}
    selected = [row for row in evidence if row.get("status") == "ok" and str(row.get("arxiv_id")) not in completed]
    if args.limit > 0:
        selected = selected[:args.limit]
    for index, row in enumerate(selected, 1):
        identifier = str(row.get("arxiv_id"))
        print(json.dumps({"status": "starting", "index": index, "total": len(selected), "arxiv_id": identifier, "model": args.model}, ensure_ascii=False), flush=True)
        command = [str(PYTHON), "-m", "src.llm.three_ai.cli", "--project-root", str(ROOT), "--evidence-archive", str(args.evidence_archive), "--analysis-archive", str(args.analysis_archive), "--arxiv-id", identifier, "--reading-model", args.model, "--opinion-model", args.model, "--copilot-bin", args.copilot_bin, "--timeout-sec", str(args.timeout_sec), "--reading-note-cache-dir", "data/runtime/local_tex_reading_cache", "--reading-chunk-cache-dir", "data/runtime/local_tex_reading_chunk_cache", "--opinion-cache-dir", "data/runtime/local_tex_opinion_cache"]
        env = os.environ.copy()
        env["PAPER_AIC_ONLY"] = "0"
        env.pop("PAPER_LLM_DIRECT_API", None)
        env["PAPER_LLM_ARTICLE_ID"] = identifier
        try:
            subprocess.run(command, cwd=ROOT, env=env, check=True)
            subprocess.run([str(PYTHON), "-m", "src.render.opinion_digest"], cwd=ROOT, env=env, check=True)
            print(json.dumps({"status": "ok", "arxiv_id": identifier}, ensure_ascii=False), flush=True)
        except subprocess.CalledProcessError as exc:
            print(json.dumps({"status": "failed", "arxiv_id": identifier, "returncode": exc.returncode}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
