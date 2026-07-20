from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from agent_alpha.config import load_yaml


def write_fac_eval_config(
    rendered_factor_files: list[str | Path],
    output_path: str | Path,
    *,
    config_path: str | Path = "configs/backtest.yaml",
    overrides: dict[str, Any] | None = None,
) -> Path:
    """Write a fac-eval-demo compatible config for rendered factor files."""
    config = load_yaml(config_path)
    if overrides:
        config.update(overrides)
    payload = {
        "trade_data_dir": config.get("trade_data_dir"),
        "output_dir": config.get("output_dir", "outputs/fac_eval"),
        "dates": config.get("dates") or [],
        "codes": config.get("codes") or [],
        "horizons": config.get("horizons") or ["ret60s"],
        "quantiles": int(config.get("quantiles", 5)),
        "min_obs_per_day": int(config.get("min_obs_per_day", 50)),
        "save_factor_outputs": bool(config.get("save_factor_outputs", False)),
        "factor_files": [
            {"path": str(Path(path).resolve()), "func": "compute_factor"}
            for path in rendered_factor_files
        ],
    }
    if config.get("factor_resample_freq"):
        payload["factor_resample_freq"] = config["factor_resample_freq"]
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out


def py_compile_factor_file(path: str | Path, *, python: str | None = None) -> subprocess.CompletedProcess[str]:
    """Compile one rendered factor file without running backtests."""
    python_bin = python or sys.executable
    return subprocess.run(
        [python_bin, "-m", "py_compile", str(path)],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def run_fac_eval_config(
    config_path: str | Path,
    *,
    run_id: str = "agent_alpha_run",
    fac_eval_project_dir: str | Path = "/home/gaozh/fac-eval-demo",
    python: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Optionally hand off a config to fac-eval-demo; evaluation logic stays there."""
    python_bin = python or sys.executable
    return subprocess.run(
        [python_bin, "-m", "py_eval.cli", "--config", str(Path(config_path).resolve()), "--run-id", run_id],
        cwd=Path(fac_eval_project_dir),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )