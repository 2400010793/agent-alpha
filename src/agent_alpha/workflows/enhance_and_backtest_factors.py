from __future__ import annotations

import argparse
import json

from agent_alpha.config import load_project_config
from agent_alpha.llm.client import LLMClient, settings_from_env
from agent_alpha.search.experiment_runner import run_search_experiment_from_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enhance, render, optionally backtest, and write feedback for high-frequency factors.")
    parser.add_argument("--candidates", required=True, help="Factor candidates JSON file or object with factor_candidates.")
    parser.add_argument("--output-dir", required=True, help="Output directory for generation summaries, feedback, and pool state.")
    parser.add_argument("--generations", type=int, default=1, help="Number of deterministic enhancement generations.")
    parser.add_argument("--metrics", default=None, help="Optional fac-eval metrics JSON/CSV/parquet to drive evaluation.")
    parser.add_argument("--run-fac-eval", action="store_true", help="Optionally call fac-eval-demo. Disabled by default.")
    parser.add_argument("--fac-eval-config-template", default="configs/backtest.yaml", help="Backtest/fac-eval template config used when writing fac-eval configs.")
    parser.add_argument("--max-new-candidates", type=int, default=20, help="Maximum enhanced candidates per generation.")
    parser.add_argument("--llm-evolution", action="store_true", help="Use the LLM factor mutation agent between generations.")
    parser.add_argument("--exploration-direction", default="", help="Current factor exploration direction for LLM mutation.")
    parser.add_argument("--api-key", default=None, help="LLM API key for --llm-evolution. If omitted, environment variables are used.")
    parser.add_argument("--model", default=None, help="LLM model override for --llm-evolution.")
    args = parser.parse_args(argv)
    client = None
    if args.llm_evolution:
        settings = settings_from_env(load_project_config().llm, api_key=args.api_key, model=args.model)
        client = LLMClient(settings)
    summary = run_search_experiment_from_file(
        args.candidates,
        output_dir=args.output_dir,
        generations=args.generations,
        run_fac_eval=args.run_fac_eval,
        metrics_path=args.metrics,
        fac_eval_config_path=args.fac_eval_config_template,
        max_new_candidates=args.max_new_candidates,
        client=client,
        exploration_direction=args.exploration_direction,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())