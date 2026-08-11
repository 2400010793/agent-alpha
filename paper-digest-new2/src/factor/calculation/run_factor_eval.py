#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


METRIC_COLUMNS = [
    "factor_name",
    "factor_field",
    "code",
    "horizon",
    "segment",
    "n_dates",
    "n_obs",
    "daily_ic",
    "daily_rankic",
    "global_ic",
    "global_rankic",
    "qspread_mean",
    "finite_ratio",
    "zero_ratio",
]


def _to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return _to_jsonable(value.item())
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return str(value)


def _resolve_config_output_dir(config_path: Path) -> Path:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raw = payload.get("output_dir", "outputs")
    output_dir = Path(str(raw)).expanduser()
    return output_dir if output_dir.is_absolute() else (config_path.parent / output_dir).resolve()


def _read_stock_level(parquet_path: Path) -> tuple[int, list[dict[str, Any]]]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("reading fac-eval parquet requires pandas and pyarrow in this Python environment") from exc

    df = pd.read_parquet(parquet_path)
    cols = [col for col in METRIC_COLUMNS if col in df.columns]
    rows = [_to_jsonable(row) for row in df[cols].to_dict(orient="records")]
    return len(df), rows


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def values(name: str) -> list[float]:
        out = []
        for row in rows:
            value = row.get(name)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                out.append(float(value))
        return out

    def mean(name: str) -> float | None:
        vals = values(name)
        return round(sum(vals) / len(vals), 6) if vals else None

    def count_ratio(name: str, predicate) -> tuple[int, float | None]:
        vals = values(name)
        count = sum(1 for value in vals if predicate(value))
        ratio = round(count / len(vals), 6) if vals else None
        return count, ratio

    positive_ic_count, positive_ic_ratio = count_ratio("daily_ic", lambda value: value > 0)
    positive_rankic_count, positive_rankic_ratio = count_ratio("daily_rankic", lambda value: value > 0)
    positive_qspread_count, positive_qspread_ratio = count_ratio("qspread_mean", lambda value: value > 0)
    ic_gt_001_count, ic_gt_001_ratio = count_ratio("daily_ic", lambda value: value > 0.01)
    ic_gt_002_count, ic_gt_002_ratio = count_ratio("daily_ic", lambda value: value > 0.02)
    ic_gt_003_count, ic_gt_003_ratio = count_ratio("daily_ic", lambda value: value > 0.03)
    abs_ic_gt_001_count, abs_ic_gt_001_ratio = count_ratio("daily_ic", lambda value: abs(value) > 0.01)
    abs_ic_gt_002_count, abs_ic_gt_002_ratio = count_ratio("daily_ic", lambda value: abs(value) > 0.02)
    abs_ic_gt_003_count, abs_ic_gt_003_ratio = count_ratio("daily_ic", lambda value: abs(value) > 0.03)

    return {
        "mean_daily_ic": mean("daily_ic"),
        "mean_daily_rankic": mean("daily_rankic"),
        "mean_global_ic": mean("global_ic"),
        "mean_global_rankic": mean("global_rankic"),
        "mean_qspread": mean("qspread_mean"),
        "mean_finite_ratio": mean("finite_ratio"),
        "mean_zero_ratio": mean("zero_ratio"),
        "total_obs": int(sum(int(row.get("n_obs") or 0) for row in rows)),
        "row_count": len(rows),
        "positive_ic_count": positive_ic_count,
        "positive_ic_ratio": positive_ic_ratio,
        "positive_rankic_count": positive_rankic_count,
        "positive_rankic_ratio": positive_rankic_ratio,
        "positive_qspread_count": positive_qspread_count,
        "positive_qspread_ratio": positive_qspread_ratio,
        "ic_gt_001_count": ic_gt_001_count,
        "ic_gt_001_ratio": ic_gt_001_ratio,
        "ic_gt_002_count": ic_gt_002_count,
        "ic_gt_002_ratio": ic_gt_002_ratio,
        "ic_gt_003_count": ic_gt_003_count,
        "ic_gt_003_ratio": ic_gt_003_ratio,
        "abs_ic_gt_001_count": abs_ic_gt_001_count,
        "abs_ic_gt_001_ratio": abs_ic_gt_001_ratio,
        "abs_ic_gt_002_count": abs_ic_gt_002_count,
        "abs_ic_gt_002_ratio": abs_ic_gt_002_ratio,
        "abs_ic_gt_003_count": abs_ic_gt_003_count,
        "abs_ic_gt_003_ratio": abs_ic_gt_003_ratio,
    }


def _write_result_json(
    *,
    result_path: Path,
    status: str,
    dedup_key: str,
    factor_file: Path,
    run_id: str,
    command: list[str],
    returncode: int | None,
    stdout: str,
    stderr: str,
    stock_level_path: Path,
    metadata_path: Path,
    rows: list[dict[str, Any]] | None = None,
    error: str = "",
) -> None:
    payload = {
        "schema_version": 1,
        "status": status,
        "dedup_key": dedup_key,
        "run_id": run_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "factor_file": str(factor_file),
        "stock_level_path": str(stock_level_path),
        "metadata_path": str(metadata_path),
        "command": command,
        "returncode": returncode,
        "stdout": stdout[-2000:],
        "stderr": stderr[-2000:],
        "error": error,
        "rows": rows or [],
        "summary": _summarize_rows(rows or []),
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(_to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _factor_files(factor_dir: Path, dedup_keys: list[str], limit: int) -> list[Path]:
    if dedup_keys:
        files = [factor_dir / f"{key}.py" for key in dedup_keys]
    else:
        files = sorted(factor_dir.glob("*.py"))
    existing = [path for path in files if path.exists()]
    return existing[:limit] if limit > 0 else existing


def run_one(
    *,
    python_bin: str,
    fac_eval_root: Path,
    config_path: Path,
    output_dir: Path,
    result_dir: Path,
    factor_file: Path,
    force: bool,
    dry_run: bool,
    timeout_sec: int,
) -> dict[str, Any]:
    dedup_key = factor_file.stem
    run_id = dedup_key
    result_path = result_dir / f"{dedup_key}.json"
    if result_path.exists() and not force:
        return {"dedup_key": dedup_key, "status": "skipped", "result_path": str(result_path)}

    command = [
        python_bin,
        "-m",
        "py_eval.cli",
        "--config",
        str(config_path),
        "--factor-file",
        str(factor_file),
        "--run-id",
        run_id,
    ]
    stock_level_path = output_dir / "factor_eval" / f"run_id={run_id}" / "stock_level.parquet"
    metadata_path = output_dir / "factor_eval" / f"run_id={run_id}" / "metadata.json"

    if dry_run:
        return {"dedup_key": dedup_key, "status": "dry_run", "command": command}

    try:
        proc = subprocess.run(
            command,
            cwd=fac_eval_root,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, timeout_sec),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _write_result_json(
            result_path=result_path,
            status="failed",
            dedup_key=dedup_key,
            factor_file=factor_file,
            run_id=run_id,
            command=command,
            returncode=None,
            stdout=str(exc.stdout or ""),
            stderr=str(exc.stderr or ""),
            stock_level_path=stock_level_path,
            metadata_path=metadata_path,
            error=f"fac-eval timeout after {timeout_sec} seconds",
        )
        return {"dedup_key": dedup_key, "status": "failed", "result_path": str(result_path), "error": "timeout"}
    if proc.returncode != 0:
        _write_result_json(
            result_path=result_path,
            status="failed",
            dedup_key=dedup_key,
            factor_file=factor_file,
            run_id=run_id,
            command=command,
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            stock_level_path=stock_level_path,
            metadata_path=metadata_path,
            error="fac-eval command failed",
        )
        return {"dedup_key": dedup_key, "status": "failed", "result_path": str(result_path)}

    rows: list[dict[str, Any]] = []
    error = ""
    status = "ok"
    try:
        _, rows = _read_stock_level(stock_level_path)
    except Exception as exc:
        status = "failed"
        error = str(exc)

    _write_result_json(
        result_path=result_path,
        status=status,
        dedup_key=dedup_key,
        factor_file=factor_file,
        run_id=run_id,
        command=command,
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        stock_level_path=stock_level_path,
        metadata_path=metadata_path,
        rows=rows,
        error=error,
    )
    return {"dedup_key": dedup_key, "status": status, "result_path": str(result_path), "rows": len(rows)}


def build_parser() -> argparse.ArgumentParser:
    script_path = Path(__file__).resolve()
    default_root = script_path.parents[2]
    default_fac_eval = default_root.parent / "fac-eval-demo"
    parser = argparse.ArgumentParser(description="Run fac-eval-demo for generated paper factor files.")
    parser.add_argument("--project-root", default=str(default_root), help="my-paper-digest project root")
    parser.add_argument("--fac-eval-root", default=os.environ.get("PAPER_FAC_EVAL_ROOT", str(default_fac_eval)))
    parser.add_argument("--config", default=os.environ.get("PAPER_FACTOR_EVAL_CONFIG", ""), help="fac-eval YAML config")
    parser.add_argument("--python", default=os.environ.get("PAPER_FACTOR_EVAL_PYTHON", "python"), help="Python executable for fac-eval-demo")
    parser.add_argument("--factor-dir", default=os.environ.get("PAPER_FACTOR_DIR", ""), help="Directory containing factor files; default is data/generated_factors")
    parser.add_argument("--result-dir", default=os.environ.get("PAPER_FACTOR_RESULT_DIR", ""), help="Directory for result JSON files; default is data/factor_results")
    parser.add_argument("--dedup-key", action="append", default=[], help="Only evaluate this generated factor stem. Can repeat.")
    parser.add_argument("--limit", type=int, default=0, help="Max factor files to evaluate; 0 means all")
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=int(os.environ.get("PAPER_FACTOR_EVAL_TIMEOUT_SEC", "1800")),
        help="Per-factor fac-eval timeout in seconds",
    )
    parser.add_argument("--force", action="store_true", help="Re-run factors with existing result JSON")
    parser.add_argument("--dry-run", action="store_true", help="Print planned commands without running fac-eval")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    fac_eval_root = Path(args.fac_eval_root).expanduser().resolve()
    config_path = Path(args.config).expanduser().resolve() if args.config else fac_eval_root / "configs" / "small_eval.yaml"
    factor_dir = Path(args.factor_dir).expanduser().resolve() if args.factor_dir else project_root / "data" / "generated_factors"
    result_dir = Path(args.result_dir).expanduser().resolve() if args.result_dir else project_root / "data" / "factor_results"

    if not fac_eval_root.exists():
        raise FileNotFoundError(f"fac-eval root not found: {fac_eval_root}")
    if not config_path.exists():
        raise FileNotFoundError(f"fac-eval config not found: {config_path}")
    output_dir = _resolve_config_output_dir(config_path)
    files = _factor_files(factor_dir, list(args.dedup_key), args.limit)
    if not files:
        raise FileNotFoundError(f"no generated factor files found in {factor_dir}")

    results = [
        run_one(
            python_bin=str(args.python),
            fac_eval_root=fac_eval_root,
            config_path=config_path,
            output_dir=output_dir,
            result_dir=result_dir,
            factor_file=factor_file,
            force=bool(args.force),
            dry_run=bool(args.dry_run),
            timeout_sec=int(args.timeout_sec),
        )
        for factor_file in files
    ]
    print(json.dumps({"status": "ok", "count": len(results), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
