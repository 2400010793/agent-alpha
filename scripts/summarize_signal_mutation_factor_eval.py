from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_RUN_DIR = Path("outputs/signal_mutation_factor_eval/run_all_mutated_signals")


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def first_candidate(run: dict[str, Any]) -> dict[str, Any]:
    candidates = run.get("initial_candidates") or []
    return dict(candidates[0]) if candidates else {}


def metric_path_for_run(run: dict[str, Any]) -> Path | None:
    summary_path = Path(str(run.get("summary_path") or ""))
    if not summary_path.exists():
        return None
    generation_summary = summary_path.parent / "iteration" / "generation_0" / "summary.json"
    if not generation_summary.exists():
        return None
    payload = load_json(generation_summary)
    metrics_path = payload.get("fac_eval_metrics_path")
    if not metrics_path:
        return None
    path = Path(str(metrics_path))
    return path if path.exists() else None


def aggregate_metric(path: Path, factor_id: str) -> dict[str, Any]:
    frame = pd.read_parquet(path)
    if "factor_name" in frame.columns:
        matched = frame[frame["factor_name"].astype(str) == factor_id]
        if not matched.empty:
            frame = matched
    return {
        "metrics_path": str(path),
        "rows": int(len(frame)),
        "n_obs_sum": int(frame["n_obs"].fillna(0).sum()) if "n_obs" in frame else None,
        "daily_ic_mean": float(frame["daily_ic"].mean()) if "daily_ic" in frame and frame["daily_ic"].notna().any() else None,
        "daily_rankic_mean": float(frame["daily_rankic"].mean()) if "daily_rankic" in frame and frame["daily_rankic"].notna().any() else None,
        "global_ic_mean": float(frame["global_ic"].mean()) if "global_ic" in frame and frame["global_ic"].notna().any() else None,
        "global_rankic_mean": float(frame["global_rankic"].mean()) if "global_rankic" in frame and frame["global_rankic"].notna().any() else None,
        "qspread_mean": float(frame["qspread_mean"].mean()) if "qspread_mean" in frame and frame["qspread_mean"].notna().any() else None,
        "finite_ratio_mean": float(frame["finite_ratio"].mean()) if "finite_ratio" in frame and frame["finite_ratio"].notna().any() else None,
        "zero_ratio_mean": float(frame["zero_ratio"].mean()) if "zero_ratio" in frame and frame["zero_ratio"].notna().any() else None,
    }


def score(metrics: dict[str, Any]) -> float | None:
    value = metrics.get("daily_rankic_mean")
    return float(value) if value is not None else None


def summarize(run_dir: Path) -> dict[str, Any]:
    overall_path = run_dir / "overall_summary.json"
    if not overall_path.exists():
        return {"status": "missing", "message": f"missing {overall_path}"}
    overall = load_json(overall_path)
    rows: list[dict[str, Any]] = []
    for run in overall.get("runs", []):
        candidate = first_candidate(run)
        factor_id = str(candidate.get("factor_id") or candidate.get("name") or "")
        metrics_path = metric_path_for_run(run)
        metrics = aggregate_metric(metrics_path, factor_id) if metrics_path and factor_id else {}
        rows.append({
            "signal_id": run.get("signal_id"),
            "original_signal_id": run.get("original_signal_id", run.get("signal_id")),
            "parent_signal_id": run.get("parent_signal_id"),
            "mutation_type": run.get("mutation_type"),
            "mutated_idea": run.get("mutated_idea"),
            "status": run.get("status"),
            "factor_id": factor_id,
            "factor_name": candidate.get("name"),
            "fields": candidate.get("fields"),
            "windows": candidate.get("windows"),
            "prefix_expression": candidate.get("prefix_expression"),
            "py_compile": candidate.get("py_compile"),
            "metrics": metrics,
        })

    baselines = {str(row["signal_id"]): row for row in rows if not row.get("parent_signal_id")}
    comparisons: list[dict[str, Any]] = []
    for row in rows:
        parent_id = row.get("parent_signal_id")
        if not parent_id:
            continue
        baseline = baselines.get(str(parent_id))
        mutation_score = score(row.get("metrics") or {})
        baseline_score = score((baseline or {}).get("metrics") or {}) if baseline else None
        delta = mutation_score - baseline_score if mutation_score is not None and baseline_score is not None else None
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

    complete_comparisons = [row for row in comparisons if row.get("delta_daily_rankic_mean") is not None]
    improved = [row for row in complete_comparisons if row.get("improved_by_rankic")]
    summary = {
        "status": overall.get("status"),
        "requested_signal_count": overall.get("requested_signal_count"),
        "completed_signal_count": overall.get("completed_signal_count"),
        "successful_signal_count": overall.get("successful_signal_count"),
        "failed_signal_count": overall.get("failed_signal_count"),
        "factor_rows": rows,
        "comparisons": comparisons,
        "complete_comparison_count": len(complete_comparisons),
        "improved_count": len(improved),
        "improvement_rate": len(improved) / len(complete_comparisons) if complete_comparisons else None,
    }
    write_json(run_dir / "mutation_improvement_summary.json", summary)

    md = [
        "# Signal Mutation Factor Evaluation Summary",
        "",
        f"status: {summary['status']}",
        f"completed: {summary['completed_signal_count']} / {summary['requested_signal_count']}",
        f"complete_comparisons: {summary['complete_comparison_count']}",
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
    (run_dir / "mutation_improvement_summary.md").write_text("\n".join(md), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize whether signal mutations improved generated factor fac-eval metrics.")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    args = parser.parse_args()
    summary = summarize(Path(args.run_dir))
    print(json.dumps({
        "status": summary.get("status"),
        "completed_signal_count": summary.get("completed_signal_count"),
        "requested_signal_count": summary.get("requested_signal_count"),
        "complete_comparison_count": summary.get("complete_comparison_count"),
        "improved_count": summary.get("improved_count"),
        "improvement_rate": summary.get("improvement_rate"),
        "summary_json": str(Path(args.run_dir) / "mutation_improvement_summary.json"),
        "summary_md": str(Path(args.run_dir) / "mutation_improvement_summary.md"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())