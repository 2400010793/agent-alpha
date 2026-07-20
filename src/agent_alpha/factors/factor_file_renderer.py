from __future__ import annotations

from pathlib import Path

from agent_alpha.factors.fac_eval_renderer import render_fac_eval_factor
from agent_alpha.factors.factor_schema import FactorCandidate


def render_factor_file(candidate: dict | FactorCandidate, output_dir: str | Path = "data/factors/rendered") -> Path:
    """Render a validated FactorCandidate to a fac-eval-compatible Python file."""
    return render_fac_eval_factor(candidate, output_dir=output_dir)