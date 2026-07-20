from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_SIGNALS_PATH = Path("outputs/signal_mutation_factor_eval/signals_for_factor_generation.json")
DEFAULT_RUN_DIR = Path("outputs/signal_mutation_factor_eval/proxy_eval_quick")


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def aggregate_metrics(metrics_path: Path) -> dict[str, dict[str, Any]]:
    frame = pd.read_parquet(metrics_path)
    out: dict[str, dict[str, Any]] = {}
    for factor_name, group in frame.groupby("factor_name"):
        out[str(factor_name)] = {
            "metrics_path": str(metrics_path),
            "rows": int(len(group)),
            "n_obs_sum": int(group["n_obs"].fillna(0).sum()),
            "daily_ic_mean": float(group["daily_ic"].mean()) if group["daily_ic"].notna().any() else None,
            "daily_rankic_mean": float(group["daily_rankic"].mean()) if group["daily_rankic"].notna().any() else None,
            "global_ic_mean": float(group["global_ic"].mean()) if group["global_ic"].notna().any() else None,
            "global_rankic_mean": float(group["global_rankic"].mean()) if group["global_rankic"].notna().any() else None,
            "qspread_mean": float(group["qspread_mean"].mean()) if group["qspread_mean"].notna().any() else None,
            "finite_ratio_mean": float(group["finite_ratio"].mean()) if group["finite_ratio"].notna().any() else None,
            "zero_ratio_mean": float(group["zero_ratio"].mean()) if group["zero_ratio"].notna().any() else None,
        }
    return out


def score(metrics: dict[str, Any]) -> float | None:
    value = metrics.get("daily_rankic_mean")
    return float(value) if value is not None else None


def summarize(signals_path: Path, run_dir: Path) -> dict[str, Any]:
    signals = load_json(signals_path).get("signals", [])
    candidates = load_json(run_dir / "proxy_factor_candidates.json").get("factor_candidates", [])
    candidate_by_signal = {str(candidate.get("source_signal_id")): candidate for candidate in candidates}
    generation_summary = load_json(run_dir / "iteration" / "generation_0" / "summary.json")
    metrics_path = Path(str(generation_summary.get("fac_eval_metrics_path") or ""))
    metrics_by_factor = aggregate_metrics(metrics_path) if metrics_path.exists() else {}

    rows: list[dict[str, Any]] = []
    for signal in signals:
        signal_id = str(signal.get("signal_id") or "")
        candidate = candidate_by_signal.get(signal_id, {})
        factor_id = str(candidate.get("factor_id") or candidate.get("name") or "")
        rows.append({
            "signal_id": signal_id,
            "original_signal_id": signal.get("_lineage_original_signal_id", signal_id),
            "parent_signal_id": signal.get("_lineage_parent_signal_id"),
            "mutation_type": signal.get("_lineage_mutation_type"),
            "mutated_idea": signal.get("_lineage_mutated_idea"),
            "factor_id": factor_id,
            "fields": candidate.get("fields"),
            "windows": candidate.get("windows"),
            "prefix_expression": candidate.get("prefix_expression"),
            "metrics": metrics_by_factor.get(factor_id, {}),
        })

    baselines = {row["signal_id"]: row for row in rows if not row.get("parent_signal_id")}
    comparisons: list[dict[str, Any]] = []
    for row in rows:
        parent_id = row.get("parent_signal_id")
        if not parent_id:
            continue
        baseline = baselines.get(str(parent_id))
        baseline_score = score((baseline or {}).get("metrics") or {}) if baseline else None
        mutation_score = score(row.get("metrics") or {})
        delta = mutation_score - baseline_score if baseline_score is not None and mutation_score is not None else None
        comparisons.append({
            "parent_signal_id": parent_id,
            "mutation_signal_id": row.get("signal_id"),
            "mutation_type": row.get("mutation_type"),
            "baseline_factor_id": (baseline or {}).get("factor_id"),
            "mutation_factor_id": row.get("factor_id"),
            "baseline_daily_rankic_mean": baseline_score,
            "mutation_daily_rankic_mean": mutation_score,
            "delta_daily_rankic_mean": delta,
            "improved_by_rankic": delta is not None and delta > 0,
            "baseline_finite_ratio_mean": ((baseline or {}).get("metrics") or {}).get("finite_ratio_mean"),
            "mutation_finite_ratio_mean": (row.get("metrics") or {}).get("finite_ratio_mean"),
            "mutated_idea": row.get("mutated_idea"),
        })

    complete = [row for row in comparisons if row.get("delta_daily_rankic_mean") is not None]
    improved = [row for row in complete if row.get("improved_by_rankic")]
    summary = {
        "signal_count": len(signals),
        "factor_count": len(candidates),
        "metrics_path": str(metrics_path),
        "rows": rows,
        "comparisons": comparisons,
        "complete_comparison_count": len(complete),
        "improved_count": len(improved),
        "improvement_rate": len(improved) / len(complete) if complete else None,
        "top_improvements": sorted(complete, key=lambda item: item.get("delta_daily_rankic_mean") or 0, reverse=True)[:10],
        "worst_changes": sorted(complete, key=lambda item: item.get("delta_daily_rankic_mean") or 0)[:10],
    }
    write_json(run_dir / "proxy_mutation_improvement_summary.json", summary)
    md = [
        "# Proxy Signal Mutation Improvement Summary",
        "",
        f"signal_count: {summary['signal_count']}",
        f"factor_count: {summary['factor_count']}",
        f"complete_comparison_count: {summary['complete_comparison_count']}",
        f"improved_count: {summary['improved_count']}",
        f"improvement_rate: {summary['improvement_rate']}",
        "",
        "## Comparisons",
        "",
    ]
    for item in comparisons:
        md.append(
            "- "
            f"{item['parent_signal_id']} -> {item['mutation_signal_id']} "
            f"({item['mutation_type']}) | "
            f"baseline={item['baseline_daily_rankic_mean']} "
            f"mutation={item['mutation_daily_rankic_mean']} "
            f"delta={item['delta_daily_rankic_mean']} "
            f"improved={item['improved_by_rankic']}"
        )
    (run_dir / "proxy_mutation_improvement_summary.md").write_text("\n".join(md), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize deterministic proxy signal mutation improvement results.")
    parser.add_argument("--signals", default=str(DEFAULT_SIGNALS_PATH))
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    args = parser.parse_args()
    summary = summarize(Path(args.signals), Path(args.run_dir))
    print(json.dumps({
        "signal_count": summary["signal_count"],
        "factor_count": summary["factor_count"],
        "complete_comparison_count": summary["complete_comparison_count"],
        "improved_count": summary["improved_count"],
        "improvement_rate": summary["improvement_rate"],
        "summary_json": str(Path(args.run_dir) / "proxy_mutation_improvement_summary.json"),
        "summary_md": str(Path(args.run_dir) / "proxy_mutation_improvement_summary.md"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())