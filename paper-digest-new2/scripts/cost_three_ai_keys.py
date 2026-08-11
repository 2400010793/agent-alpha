#!/usr/bin/env python3
"""Multi-model cost and smoke test for the active two-stage workflow.

Default matrix: key1/gpt-4o, key2/gpt-4.1, key3/gpt-4.1-mini.
Stages: reading and generic Graph/Auto-Research analysis.
No API call occurs without --run-llm. Live runs wait 1800 seconds between models.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.llm.three_ai.pipeline as three_ai_pipeline  # noqa: E402
from src.llm.three_ai.pipeline import (  # noqa: E402
    build_reading_chunks,
    build_reading_note_single_call_chunked,
    read_jsonl_valid,
)
from src.llm.three_ai.opinion_analysis import RESEARCH_ANALYSIS_SCHEMA, generate_article_opinions  # noqa: E402


def estimate_tokens(value: object) -> int:
    return max(1, round(len(json.dumps(value, ensure_ascii=False)) / 4))


def load_prices(path: Path) -> Dict[str, Dict[str, float]]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required for config/model_prices.yaml") from exc
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("prices", {})


def cost_usd(model: str, input_tokens: int, output_tokens: int, prices: Dict[str, Dict[str, float]]) -> float:
    price = prices.get(model)
    if not price:
        raise RuntimeError(f"model {model!r} is missing from model_prices.yaml")
    return (input_tokens * float(price["input_per_1m"]) + output_tokens * float(price["output_per_1m"])) / 1_000_000


def actual_usage_cost(model: str, usage: object, prices: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
    usage_dict = usage if isinstance(usage, dict) else {}
    prompt = int(usage_dict.get("prompt_tokens") or 0)
    completion = int(usage_dict.get("completion_tokens") or 0)
    total = int(usage_dict.get("total_tokens") or prompt + completion)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "actual_cost_usd": round(cost_usd(model, prompt, completion, prices), 8),
        "cost_source": "upstream_usage",
    }


def trusted_article(rows: List[Dict[str, Any]], arxiv_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    candidates = reversed(rows) if not arxiv_id else rows
    for row in candidates:
        pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
        quality = pack.get("quality_checks") if isinstance(pack.get("quality_checks"), dict) else {}
        found_id = str(row.get("arxiv_id") or pack.get("arxiv_id") or "")
        if pack.get("status") == "ok" and quality.get("is_trusted") and (not arxiv_id or found_id == arxiv_id):
            return row, pack
    raise RuntimeError(f"no trusted evidence row found for arxiv_id={arxiv_id!r}")


def parse_matrix(raw: str) -> List[Dict[str, str]]:
    matrix = []
    for item in raw.split(","):
        model, key_env = item.strip().split(":", 1)
        matrix.append({"model": model.strip(), "key_env": key_env.strip()})
    if not matrix:
        raise ValueError("empty model matrix")
    return matrix


def load_key_env_file(path: Path, names: List[str]) -> None:
    """Load only requested key assignments without printing their values."""
    if not path.exists():
        return
    wanted = set(names)
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in wanted or os.environ.get(name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            os.environ[name] = value


def main() -> None:
    parser = argparse.ArgumentParser(description="Run/estimate three models through all three AI stages.")
    parser.add_argument("--arxiv-id", default="", help="Trusted article id; default is latest trusted article.")
    parser.add_argument("--run-llm", action="store_true", help="Actually call APIs; default is offline dry-run.")
    parser.add_argument("--wait-sec", type=int, default=1800, help="Delay between model runs, default 1800 seconds.")
    parser.add_argument("--copilot-bin", default="/home/gaozh/bin/copilot")
    parser.add_argument("--timeout-sec", type=int, default=600)
    parser.add_argument("--env-file", default="/home/gaozh/my-paper-digest-new/deploy/systemd/paper.env", help="Optional env file containing key1/key2/key3.")
    parser.add_argument("--matrix", default="gpt-4o:PAPER_LLM_API_KEY,gpt-4.1:PAPER_LLM_API_KEY2,gpt-4.1-mini:PAPER_LLM_API_KEY3", help="MODEL:KEY_ENV pairs separated by commas.")
    args = parser.parse_args()

    matrix = parse_matrix(args.matrix)
    load_key_env_file(Path(args.env_file).expanduser(), [item["key_env"] for item in matrix])
    rows = read_jsonl_valid(ROOT / "data" / "arxiv_evidence_archive.jsonl")
    row, pack = trusted_article(rows, args.arxiv_id)
    prices = load_prices(ROOT / "config" / "model_prices.yaml")
    reading_input = estimate_tokens(build_reading_chunks(row, pack))
    stage_estimates = {
        "reading": (reading_input, 3500),
        "opinion_analysis": (3500, 2000),
    }

    print(json.dumps({"mode": "live" if args.run_llm else "dry_run", "article_id": row.get("arxiv_id"), "title": row.get("title"), "matrix": matrix, "wait_sec_between_models": args.wait_sec, "stage_token_estimates": stage_estimates}, ensure_ascii=False, indent=2))
    results: List[Dict[str, Any]] = []

    for index, config in enumerate(matrix):
        model, key_env = config["model"], config["key_env"]
        stages = {
            name: {"input_tokens_est": inputs, "output_tokens_est": outputs, "cost_usd_est": round(cost_usd(model, inputs, outputs, prices), 6)}
            for name, (inputs, outputs) in stage_estimates.items()
        }
        result: Dict[str, Any] = {"model": model, "key_env": key_env, "env_present": bool(os.environ.get(key_env)), "article_id": row.get("arxiv_id"), "title": row.get("title"), "stages": stages, "total_cost_usd_est": round(sum(item["cost_usd_est"] for item in stages.values()), 6)}
        print(f"\n[{index + 1}/{len(matrix)}] {model} via {key_env}; estimated total=${result['total_cost_usd_est']}")

        if args.run_llm:
            os.environ["PAPER_LLM_DIRECT_API"] = "1"
            if not result["env_present"]:
                result["error"] = f"missing environment variable: {key_env}"
                print(f"  SKIP: {result['error']}")
            else:
                try:
                    started = time.time()
                    note = build_reading_note_single_call_chunked(row, pack, model=model, copilot_bin=args.copilot_bin, timeout_sec=args.timeout_sec, api_key_env=key_env)
                    stages["reading"].update({"elapsed_sec": round(time.time() - started, 2), "output_chars": len(json.dumps(note, ensure_ascii=False)), "json_valid": True, "schema_valid": note.get("schema_version") == "reading_note_v1"})
                    stages["reading"].update(actual_usage_cost(model, three_ai_pipeline.LAST_LLM_USAGE, prices))
                    started = time.time()
                    opinions = generate_article_opinions(row, note, three_ai_pipeline.build_evidence_pack_v2(pack), copilot_json=three_ai_pipeline.copilot_json, model=model, copilot_bin=args.copilot_bin, timeout_sec=args.timeout_sec, api_key_env=key_env)
                    stages["opinion_analysis"].update({"elapsed_sec": round(time.time() - started, 2), "output_chars": len(json.dumps(opinions, ensure_ascii=False)), "json_valid": True, "schema_valid": opinions.get("schema_version") == RESEARCH_ANALYSIS_SCHEMA, "validation_status": (opinions.get("analysis_validation") or {}).get("status")})
                    stages["opinion_analysis"].update(actual_usage_cost(model, three_ai_pipeline.LAST_LLM_USAGE, prices))
                    result["total_tokens"] = sum(stage.get("total_tokens", 0) for stage in stages.values())
                    result["actual_cost_usd"] = round(sum(stage.get("actual_cost_usd", 0.0) for stage in stages.values()), 8)
                    result["cost_source"] = "upstream_usage"
                    print("  OK: reading -> generic_graph_research_analysis")
                except Exception as exc:
                    result["error"] = str(exc)
                    print(f"  ERROR: {exc}")
            if index + 1 < len(matrix):
                print(f"  Waiting {args.wait_sec} seconds before the next model run...")
                time.sleep(max(0, args.wait_sec))
        results.append(result)

    output = ROOT / "reports" / "three_ai_cost_by_model.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {output}")


if __name__ == "__main__":
    main()
