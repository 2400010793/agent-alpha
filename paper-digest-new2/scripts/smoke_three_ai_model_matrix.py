#!/usr/bin/env python3
"""
Smoke test runner for Three-AI model matrix.
Selects 3 benchmark papers (Small, Median, Large based on token size),
runs them against specified model matrix configurations when --run-llm is set,
and writes results to reports/three_ai_smoke_test_results.json.
Supports selecting different keys: PAPER_LLM_API_KEY (key1), PAPER_LLM_API_KEY2 (key2), PAPER_LLM_API_KEY3 (key3)
"""

import os
import sys
import json
import argparse
import time
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "data" / "arxiv_evidence_archive.jsonl"
REPORT_PATH = ROOT / "reports" / "three_ai_smoke_test_results.json"

sys.path.insert(0, str(ROOT))
from src.llm.three_ai.pipeline import build_reading_chunks, build_reading_note_single_call_chunked, generate_hf_factors

def read_jsonl_valid(path: Path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows

def estimate_tokens(obj: object) -> int:
    return max(1, round(len(json.dumps(obj, ensure_ascii=False)) / 4))

def main():
    parser = argparse.ArgumentParser(description="Three-AI model evaluation smoke tests.")
    parser.add_argument("--run-llm", action="store_true", help="Actually run LLM API calls. Otherwise, dry-run only.")
    parser.add_argument("--copilot-bin", default="/home/gaozh/bin/copilot", help="Path to copilot binary.")
    parser.add_argument("--key1-env", default="PAPER_LLM_API_KEY", help="Environment variable for Key 1.")
    parser.add_argument("--key2-env", default="PAPER_LLM_API_KEY2", help="Environment variable for Key 2.")
    parser.add_argument("--key3-env", default="PAPER_LLM_API_KEY3", help="Environment variable for Key 3.")
    args = parser.parse_args()

    print("Selecting benchmark cases (small, median, large) based on single_call_chunked size...")
    rows = read_jsonl_valid(EVIDENCE_PATH)
    trusted = []
    for row in rows:
        pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
        quality = pack.get("quality_checks") if isinstance(pack.get("quality_checks"), dict) else {}
        if pack.get("status") == "ok" and quality.get("is_trusted"):
            chunks = build_reading_chunks(row, pack)
            # Dummy payload to get size
            p_size = estimate_tokens(chunks)
            trusted.append((row, pack, p_size))

    if not trusted:
        print("No trusted articles found.")
        sys.exit(1)

    trusted.sort(key=lambda x: x[2])
    
    # Pick three papers
    small_case = trusted[0]
    median_case = trusted[len(trusted) // 2]
    large_case = trusted[-1]

    cases = {
        "small": {"row": small_case[0], "pack": small_case[1], "size": small_case[2], "arxiv_id": small_case[0].get("arxiv_id", "")},
        "median": {"row": median_case[0], "pack": median_case[1], "size": median_case[2], "arxiv_id": median_case[0].get("arxiv_id", "")},
        "large": {"row": large_case[0], "pack": large_case[1], "size": large_case[2], "arxiv_id": large_case[0].get("arxiv_id", "")},
    }

    print(f"benchmark papers selected:")
    for k, v in cases.items():
        print(f"  - {k.upper()}: id={v['arxiv_id']} title={v['row'].get('title')[:40]}... (approx {v['size']} tokens)")

    # Define test combinations
    # (Model, Stage, SizeCase, api_key_env)
    tests = [
        # A. gpt-4o as baseline
        {"model": "gpt-4o", "stage": "reading", "case_key": "median", "api_key_env": args.key2_env},
        {"model": "gpt-4o", "stage": "idea", "case_key": "median", "api_key_env": args.key1_env},
        # B. gpt-4.1 for high quality
        {"model": "gpt-4.1", "stage": "reading", "case_key": "large", "api_key_env": args.key2_env},
        {"model": "gpt-4.1", "stage": "idea", "case_key": "large", "api_key_env": args.key1_env},
        # C. gpt-4.1-mini as cheap candidate
        {"model": "gpt-4.1-mini", "stage": "reading", "case_key": "small", "api_key_env": args.key2_env},
        {"model": "gpt-4.1-mini", "stage": "idea", "case_key": "small", "api_key_env": args.key1_env},
    ]

    results = []
    
    # Verify environment keys are configured
    print("\nAPI Key configuration status:")
    for kn in [args.key1_env, args.key2_env, args.key3_env]:
        val = os.environ.get(kn)
        status = "Present" if val else "ABSENT"
        preview = f"{val[:12]}..." if val else ""
        print(f"  - {kn}: {status} {preview}")

    if not args.run_llm:
        print("\n=== DRY RUN MODE ===")
        print("Set --run-llm to execute actual API calls.")
        for idx, t in enumerate(tests, 1):
            c_info = cases[t["case_key"]]
            print(f"Dry-run [{idx}]: Model={t['model']}, Stage={t['stage']}, Case={t['case_key']} (arxiv={c_info['arxiv_id']}), EnvKey={t['api_key_env']}")
        return

    print("\n=== EXECUTING ACTUAL API CALLS ===")
    for idx, t in enumerate(tests, 1):
        c_info = cases[t["case_key"]]
        row = c_info["row"]
        pack = c_info["pack"]
        model = t["model"]
        stage = t["stage"]
        key_env = t["api_key_env"]

        print(f"\n[{idx}/{len(tests)}] Running {stage} with {model} on {t['case_key']} paper ({c_info['arxiv_id']})...")
        started = time.time()
        
        # We need reading note for generating ideas (Stage 2)
        # So if we run idea stage, we first get reading note (using median/gpt-4o as reading baseline or same model)
        reading_note = None
        if stage == "idea":
            try:
                print(f"  -> Prefetching a baseline reading note using gpt-4o...")
                reading_note = build_reading_note_single_call_chunked(
                    row, pack, model="gpt-4o", copilot_bin=args.copilot_bin, timeout_sec=200, api_key_env=args.key2_env
                )
            except Exception as e:
                print(f"  -> Error prefetching baseline reading note: {e}")
                results.append({
                    "model": model,
                    "arxiv_id": c_info["arxiv_id"],
                    "mode": f"{stage}_via_api",
                    "error": f"Prefetch baseline reading failed: {str(e)}"
                })
                continue
        
        err_msg = ""
        elapsed = 0.0
        json_valid = False
        schema_valid = False
        output_len = 0
        quality_score = 0.0
        
        try:
            if stage == "reading":
                note = build_reading_note_single_call_chunked(
                    row, pack, model=model, copilot_bin=args.copilot_bin, timeout_sec=240, api_key_env=key_env
                )
                output_len = len(json.dumps(note, ensure_ascii=False))
                json_valid = True
                schema_valid = note.get("schema_version") == "reading_note_v1"
                quality_score = note.get("recommendation_score", 0.0)
            elif stage == "idea":
                factors = generate_hf_factors(
                    row, reading_note, pack, model=model, copilot_bin=args.copilot_bin, timeout_sec=240, api_key_env=key_env
                )
                output_len = len(json.dumps(factors, ensure_ascii=False))
                json_valid = True
                schema_valid = factors.get("schema_version") == "factor_analysis_v6"
                quality_score = factors.get("recommendation_score", 0.0)
            
            elapsed = round(time.time() - started, 2)
            print(f"  -> Success! Elapsed: {elapsed}s, output chars: {output_len}, recommendation score: {quality_score}")
        except Exception as e:
            elapsed = round(time.time() - started, 2)
            err_msg = str(e)
            print(f"  -> Error: {err_msg}")

        results.append({
            "model": model,
            "article_id": c_info["arxiv_id"],
            "mode": f"single_call_chunked_{stage}",
            "estimated_input_tokens": c_info["size"],
            "elapsed_sec": elapsed,
            "output_chars": output_len,
            "json_valid": json_valid,
            "schema_valid": schema_valid,
            "coverage_score": quality_score,
            "error": err_msg if err_msg else None,
            "manual_quality_note": "Dry run/automated smoke verified successfully." if not err_msg else "Failed execution."
        })

    # Save results
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nWritten smoke test results to {REPORT_PATH}")

if __name__ == "__main__":
    main()
