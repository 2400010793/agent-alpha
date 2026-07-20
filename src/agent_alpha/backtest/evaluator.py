from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_alpha.config import load_yaml
from agent_alpha.factors.fac_eval_adapter import run_fac_eval_config, write_fac_eval_config


def run_fac_eval(
    fac_eval_config: str | Path,
    *,
    run_id: str = "agent_alpha_run",
    fac_eval_project_dir: str | Path | None = None,
    python: str | None = None,
) -> dict[str, Any]:
    """Optional adapter that delegates evaluation to fac-eval-demo."""
    backtest_config = load_yaml("configs/backtest.yaml")
    project_dir = Path(fac_eval_project_dir or backtest_config.get("fac_eval_project_dir") or "/home/gaozh/fac-eval-demo")
    python_bin = python or str(backtest_config.get("python") or "python")
    proc = run_fac_eval_config(fac_eval_config, run_id=run_id, fac_eval_project_dir=project_dir, python=python_bin)
    return {
        "command": proc.args,
        "cwd": str(project_dir),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "ok": proc.returncode == 0,
        }

def write_fac_eval_result(path: str | Path, result: dict[str, Any]) -> None:
    import json

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = ["run_fac_eval", "write_fac_eval_config", "write_fac_eval_result"]