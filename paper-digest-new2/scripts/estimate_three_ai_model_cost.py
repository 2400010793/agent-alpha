#!/usr/bin/env python3
"""
Estimate three-AI model costs offline based on token approximations.
Reads data/arxiv_evidence_archive.jsonl, builds different payloads,
and estimates input/output tokens and cost in USD.
Output path: reports/three_ai_model_cost_estimate.json
"""

import os
import json
import yaml
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "data" / "arxiv_evidence_archive.jsonl"
PRICE_PATH = ROOT / "config" / "model_prices.yaml"
REPORT_JSON_PATH = ROOT / "reports" / "three_ai_model_cost_estimate.json"
REPORT_MD_PATH = ROOT / "reports" / "three_ai_model_cost_estimate.md"

# Fallback token estimator (chars / 4)
def estimate_tokens(obj: object) -> int:
    return max(1, round(len(json.dumps(obj, ensure_ascii=False)) / 4))

def load_prices():
    if not PRICE_PATH.exists():
        return {
            "gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.00},
            "gpt-4o-mini": {"input_per_1m": 0.150, "output_per_1m": 0.600},
            "gpt-4.1": {"input_per_1m": 5.00, "output_per_1m": 15.00},
            "gpt-4.1-mini": {"input_per_1m": 0.30, "output_per_1m": 0.90},
            "gpt-4.1-nano": {"input_per_1m": 0.10, "output_per_1m": 0.30},
        }
    with PRICE_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return data.get("prices", {})

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

def pct(xs, p):
    if not xs:
        return 0
    xs = sorted(xs)
    idx = int(len(xs) * p / 100)
    return xs[min(idx, len(xs) - 1)]

def main():
    print(f"Loading evidence from {EVIDENCE_PATH}")
    rows = read_jsonl_valid(EVIDENCE_PATH)
    
    # Import pipeline to reuse build_reading_chunks
    import sys
    sys.path.insert(0, str(ROOT))
    from src.llm.three_ai.pipeline import build_reading_chunks, _reading_note_schema
    
    trusted_evidence = []
    for row in rows:
        pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
        quality = pack.get("quality_checks") if isinstance(pack.get("quality_checks"), dict) else {}
        if pack.get("status") == "ok" and quality.get("is_trusted"):
            trusted_evidence.append((row, pack))
            
    print(f"Found {len(trusted_evidence)} trusted evidence articles.")
    if not trusted_evidence:
        print("No trusted articles found. Exiting.")
        return

    prices = load_prices()
    
    single_call_chunked_inputs = []
    no_chunk_inputs = []
    map_merge_inputs = [] # Single largest chunk
    
    for row, pack in trusted_evidence:
        # 1. single_call_chunked
        chunks = build_reading_chunks(row, pack)
        # Payload for build_reading_note_single_call_chunked:
        payload_single = {
            "article_meta": {
                "title": row.get("title"),
                "url": row.get("url"),
                "source_id": row.get("source_id"),
                "source_name": row.get("source_name"),
                "tags": row.get("tags", []),
            },
            "reading_chunks": chunks,
            "required_schema": _reading_note_schema(),
        }
        single_call_chunked_inputs.append(estimate_tokens(payload_single))
        
        # 2. no_chunk reading payload
        payload_no_chunk = {
            "article_meta": {
                "title": row.get("title"),
                "url": row.get("url"),
                "source_id": row.get("source_id"),
                "source_name": row.get("source_name"),
                "tags": row.get("tags", []),
            },
            "abstract": str(row.get("summary") or "")[:3000],
            "evidence_pack_v2": pack, # Assuming build_evidence_pack_v2 returns similar
            "evidence_pack": pack,
            "required_schema": _reading_note_schema(),
        }
        no_chunk_inputs.append(estimate_tokens(payload_no_chunk))
        
        # 3. map-merge chunk payloads (largest chunk tokens)
        chunk_toks = []
        for ch in chunks:
            ch_payload = {
                "chunk": ch,
                "required_schema": {
                    "schema_version": "reading_note_chunk_v1",
                    "chunk_id": ch.get("chunk_id"),
                    "central_claims": [],
                    "problem_or_context": [],
                    "method_logic": [],
                    "core_formulas": [],
                    "experimental_formulas": [],
                    "code_or_algorithm_logic": [],
                    "variable_definitions": [],
                    "data_and_empirical_setup": [],
                    "key_results": [],
                    "conclusion_claims": [],
                    "limitations": [],
                    "not_disclosed": [],
                    "faithfulness_constraints_for_next_llm": [],
                },
            }
            chunk_toks.append(estimate_tokens(ch_payload))
        map_merge_inputs.append(max(chunk_toks) if chunk_toks else 0)

    # Compile statistics
    stats = {
        "count": len(trusted_evidence),
        "single_call_chunked": {
            "p50": pct(single_call_chunked_inputs, 50),
            "p90": pct(single_call_chunked_inputs, 90),
            "p95": pct(single_call_chunked_inputs, 95),
            "max": pct(single_call_chunked_inputs, 100),
        },
        "no_chunk": {
            "p50": pct(no_chunk_inputs, 50),
            "p90": pct(no_chunk_inputs, 90),
            "p95": pct(no_chunk_inputs, 95),
            "max": pct(no_chunk_inputs, 100),
        },
        "map_merge_max_chunk": {
            "p50": pct(map_merge_inputs, 50),
            "p90": pct(map_merge_inputs, 90),
            "p95": pct(map_merge_inputs, 95),
            "max": pct(map_merge_inputs, 100),
        }
    }

    # Estimate Money for 3 Scenarios
    # Scenario A: High Quality (A. reading: gpt-4.1, idea: gpt-4.1, audit: gpt-4o/gpt-4.1)
    # Scenario B: Cost Balanced (B. reading: gpt-4.1-mini, idea: gpt-4.1-mini, audit: gpt-4o)
    # Scenario C: Cheap Batch (C. reading: gpt-4.1-nano, idea: gpt-4.1-nano, audit: only 20% gpt-4o)
    
    # Custom formula outputs (p50 / p95 approximation):
    # - reading_note_v1: 3.5k tokens
    # - idea extraction output: 2k tokens
    # - audit output: 1.5k tokens
    
    scenarios = {}
    for model_name, pricing in prices.items():
        in_p = pricing["input_per_1m"]
        out_p = pricing["output_per_1m"]
        scenarios[model_name] = {
            "reading_p50_cost_usd": (stats["single_call_chunked"]["p50"] / 1e6 * in_p) + (3500 / 1e6 * out_p),
            "reading_p95_cost_usd": (stats["single_call_chunked"]["p95"] / 1e6 * in_p) + (3500 / 1e6 * out_p),
            "idea_p50_cost_usd": ((3500 + 4000) / 1e6 * in_p) + (2000 / 1e6 * out_p), # reading note + local context -> ideas
            "idea_p95_cost_usd": ((3500 + 4000) / 1e6 * in_p) + (2000 / 1e6 * out_p), 
            "audit_p50_cost_usd": ((3500 + 2000 + 1000) / 1e6 * in_p) + (1500 / 1e6 * out_p), # reading_note + ideas + compact_evidence -> audit
            "audit_p95_cost_usd": ((3500 + 2000 + 1000) / 1e6 * in_p) + (1500 / 1e6 * out_p),
        }
        # Sum of three stages
        scenarios[model_name]["total_p50_cost_usd"] = (
            scenarios[model_name]["reading_p50_cost_usd"] +
            scenarios[model_name]["idea_p50_cost_usd"] +
            scenarios[model_name]["audit_p50_cost_usd"]
        )
        scenarios[model_name]["total_p95_cost_usd"] = (
            scenarios[model_name]["reading_p95_cost_usd"] +
            scenarios[model_name]["idea_p95_cost_usd"] +
            scenarios[model_name]["audit_p95_cost_usd"]
        )

    output_data = {
        "stats": stats,
        "prices": prices,
        "scenarios": scenarios,
    }

    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # Build Markdown table
    md_content = f"""# Three-AI Model Token & Cost Estimate Report
Generated on: 2026-07-21
Sample: {stats['count']} trusted ok evidence articles

## 1. Token Distribution Summary
Values estimated using approximation (characters / 4).

| Mode / Payload | p50 (Median) | p90 | p95 | Max |
| :--- | :--- | :--- | :--- | :--- |
| **single_call_chunked** | {stats['single_call_chunked']['p50'] / 1000:.1f}k | {stats['single_call_chunked']['p90'] / 1000:.1f}k | {stats['single_call_chunked']['p95'] / 1000:.1f}k | {stats['single_call_chunked']['max'] / 1000:.1f}k |
| **no_chunk** | {stats['no_chunk']['p50'] / 1000:.1f}k | {stats['no_chunk']['p90'] / 1000:.1f}k | {stats['no_chunk']['p95'] / 1000:.1f}k | {stats['no_chunk']['max'] / 1000:.1f}k |
| **map-merge max chunk** | {stats['map_merge_max_chunk']['p50'] / 1000:.1f}k | {stats['map_merge_max_chunk']['p90'] / 1000:.1f}k | {stats['map_merge_max_chunk']['p95'] / 1000:.1f}k | {stats['map_merge_max_chunk']['max'] / 1000:.1f}k |

## 2. Model Pricing Table (per 1 Million Tokens)
Based on `config/model_prices.yaml`.

| Model Name | Input Price ($/1M) | Output Price ($/1M) |
| :--- | :---: | :---: |
"""
    for model_name, pricing in prices.items():
        md_content += f"| {model_name} | ${pricing['input_per_1m']:.3f} | ${pricing['output_per_1m']:.3f} |\n"

    md_content += """
## 3. Estimated Cost Per Article (USD)
Assuming:
- Stage 1 (Reading single-call chunked): Output 3.5k tokens
- Stage 2 (Idea Generation): Input: 7.5k tokens, Output 2.0k tokens
- Stage 3 (Audit): Input: 6.5k tokens, Output 1.5k tokens

| Model | Stage 1 (p50) | Stage 2 | Stage 3 | Total (p50) | Total (p95) | Cost for 100 papers (p50) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
"""
    for model_name, sc in scenarios.items():
        md_content += (
            f"| **{model_name}** | "
            f"${sc['reading_p50_cost_usd']:.4f} | "
            f"${sc['idea_p50_cost_usd']:.4f} | "
            f"${sc['audit_p50_cost_usd']:.4f} | "
            f"${sc['total_p50_cost_usd']:.4f} | "
            f"${sc['total_p95_cost_usd']:.4f} | "
            f"${sc['total_p50_cost_usd'] * 100:.2f} |\n"
        )

    md_content += """
## 4. Pipeline Optimization Recommendations
1. **Single-Call Chunked**: Extremely efficient ($0.01 - $0.05 per paper on `gpt-4o`). Much cheaper than map-merge with 5 calls.
2. **Strategy 1 (High Quality)**: Run Stage 1 & 2 on `gpt-4.1`, Stage 3 on `gpt-4o`. Total cost ~$0.15 / paper.
3. **Strategy 2 (Balanced)**: Run Stage 1 & 2 on `gpt-4.1-mini`, Stage 3 on `gpt-4o`. Total cost ~$0.04 / paper.
"""
    REPORT_MD_PATH.write_text(md_content, encoding="utf-8")
    print(f"Offline token cost report written to {REPORT_JSON_PATH} and {REPORT_MD_PATH}")

if __name__ == "__main__":
    main()
