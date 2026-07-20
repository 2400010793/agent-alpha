from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

from agent_alpha.factors.expression_validator import validate_factor_candidate
from agent_alpha.search.experiment_runner import run_search_experiment


DEFAULT_SIGNALS_PATH = Path("outputs/signal_mutation_factor_eval/signals_for_factor_generation.json")
DEFAULT_OUTPUT_DIR = Path("outputs/signal_mutation_factor_eval/proxy_eval")
DEFAULT_FAC_EVAL_TEMPLATE = Path("/home/gaozh/fac-eval-demo/configs/small_eval.yaml")


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_quick_fac_eval_template(source: str | Path, output_path: str | Path) -> Path:
    payload = yaml.safe_load(Path(source).read_text(encoding="utf-8")) or {}
    payload["dates"] = list(payload.get("dates") or [])[:5]
    payload["codes"] = list(payload.get("codes") or [])[:5]
    payload["output_dir"] = "../outputs_quick"
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()[:96] or "signal"


def depute_ratio_prefix() -> list[Any]:
    return [
        "safe_div",
        ["sub", "totalDeputeBuy", "totalDeputeSell"],
        ["add", ["abs", "totalDeputeBuy"], ["abs", "totalDeputeSell"]],
    ]


def base_prefix_for_signal(signal: dict[str, Any]) -> tuple[list[Any], list[str], list[int], list[str]]:
    tags = {str(tag) for tag in signal.get("hf_mechanism_tags", [])}
    text = " ".join(
        str(signal.get(key, ""))
        for key in ("signal_id", "signal_name", "market_intuition", "hypothesis", "_lineage_mutated_idea")
    ).casefold()

    if "hidden_liquidity" in tags or "depute" in text:
        prefix: list[Any] = ["zscore", depute_ratio_prefix(), 60]
        fields = ["totalDeputeBuy", "totalDeputeSell"]
        windows = [60]
        tags_out = ["hidden_liquidity"]
        if "spread" in text or "spread_liquidity" in tags:
            prefix = ["mul", ["tanh", prefix], ["zscore", "spread_l1", 60]]
            fields.append("spread_l1")
            tags_out.append("spread_liquidity")
        elif "depth" in text or "order_book_pressure" in tags or "order_imbalance" in tags:
            prefix = ["mul", prefix, ["zscore", "depth_imbalance_l1", 60]]
            fields.append("depth_imbalance_l1")
            tags_out.append("order_book_pressure")
        return prefix, fields, windows, tags_out

    if "volatility_burst" in tags or "volatility" in text or "liquidity" in text:
        return ["mul", ["zscore", "spread_l1", 60], ["zscore", "log_volume", 60]], ["spread_l1", "log_volume"], [60], ["spread_liquidity", "trade_impact"]

    if "trade_impact" in tags or "spread" in text:
        return ["mul", ["zscore", "depth_imbalance_l1", 60], ["zscore", "relative_spread_l1", 60]], ["depth_imbalance_l1", "relative_spread_l1"], [60], ["order_book_pressure", "spread_liquidity"]

    return ["zscore", "depth_imbalance_l1", 60], ["depth_imbalance_l1"], [60], ["order_book_pressure"]


def factor_for_signal(signal: dict[str, Any]) -> dict[str, Any]:
    prefix, fields, windows, tags = base_prefix_for_signal(signal)
    signal_id = str(signal.get("signal_id") or "signal")
    text = " ".join(str(signal.get(key, "")) for key in ("signal_id", "signal_name", "hypothesis", "_lineage_mutated_idea")).casefold()
    if "reversal" in text or str(signal.get("expected_direction") or "").casefold() == "negative":
        prefix = ["neg", prefix]
    if "extreme" in text:
        prefix = ["where", ["gt", ["abs", "depth_imbalance_l1"], 0.5], prefix, 0.0]
        if "depth_imbalance_l1" not in fields:
            fields.append("depth_imbalance_l1")
    factor_id = f"proxy_{safe_id(signal_id)}"
    candidate = {
        "factor_id": factor_id,
        "name": factor_id,
        "prefix_expression": prefix,
        "fields": fields,
        "windows": windows,
        "direction": str(signal.get("expected_direction") or "unknown"),
        "source_signal_id": signal_id,
        "source_reading_note_id": str(signal.get("source_reading_note_id") or signal.get("source_paper_id") or ""),
        "mechanism_tags": tags,
        "economic_rationale": str(signal.get("market_intuition") or signal.get("hypothesis") or ""),
        "created_by": "signal_mutation_proxy_eval",
    }
    validation = validate_factor_candidate(candidate)
    candidate["validation_status"] = "passed" if validation.ok else "failed"
    candidate["validation_message"] = validation.message
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic proxy factors for parent and mutated signals, then run fac-eval.")
    parser.add_argument("--signals", default=str(DEFAULT_SIGNALS_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--fac-eval-config-template", default=str(DEFAULT_FAC_EVAL_TEMPLATE))
    parser.add_argument("--quick", action="store_true", help="Use a tiny date/code subset for a fast directional check.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    signals = load_json(args.signals).get("signals", [])
    candidates = [factor_for_signal(signal) for signal in signals]
    passed = [candidate for candidate in candidates if candidate.get("validation_status") == "passed"]
    write_json(output_dir / "proxy_factor_candidates.json", {"factor_candidates": candidates})
    fac_eval_template = Path(args.fac_eval_config_template)
    if args.quick:
        fac_eval_template = write_quick_fac_eval_template(fac_eval_template, output_dir / "quick_fac_eval_template.yaml")
    summary = run_search_experiment(
        passed,
        output_dir=output_dir / "iteration",
        generations=1,
        run_fac_eval=True,
        fac_eval_config_path=fac_eval_template,
        metrics_path=None,
        max_new_candidates=0,
        client=None,
        exploration_direction="deterministic proxy evaluation for signal mutation improvement",
    )
    write_json(output_dir / "summary.json", {"signal_count": len(signals), "candidate_count": len(candidates), "passed_candidate_count": len(passed), "iteration": summary})
    print(json.dumps({"signal_count": len(signals), "candidate_count": len(candidates), "passed_candidate_count": len(passed), "summary": str(output_dir / "summary.json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())