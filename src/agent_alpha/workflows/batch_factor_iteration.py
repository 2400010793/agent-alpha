from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent_alpha.config import load_project_config
from agent_alpha.factors.expression_validator import validate_factor_candidate
from agent_alpha.factors.fac_eval_adapter import py_compile_factor_file, write_fac_eval_config
from agent_alpha.factors.factor_file_renderer import render_factor_file
from agent_alpha.factors.llm_factor_generator import generate_factor_candidates_with_llm
from agent_alpha.llm.client import LLMClient, settings_from_env
from agent_alpha.search.signal_mutation import generate_signal_mutations
from agent_alpha.search.experiment_runner import run_search_experiment


def _load_signals(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        signals = payload.get("signals", [])
    else:
        signals = payload
    if not isinstance(signals, list):
        raise ValueError("signals file must be a list or an object with key 'signals'")
    return [dict(signal) for signal in signals if isinstance(signal, dict)]


def _load_factor_candidates(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    candidates = payload.get("factor_candidates", payload.get("candidates", [])) if isinstance(payload, dict) else payload
    if not isinstance(candidates, list):
        raise ValueError("factor candidate input must be a list or an object with factor_candidates")
    return [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]


def _mutate_signals(
    signals: list[dict[str, Any]],
    client: LLMClient,
    *,
    max_signal_mutations_per_signal: int,
    exploration_direction: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if max_signal_mutations_per_signal <= 0:
        return signals, []
    mutation_records: list[dict[str, Any]] = []
    mutated_signals: list[dict[str, Any]] = []
    for signal in signals:
        records = generate_signal_mutations(
            signal,
            client,
            exploration_direction=exploration_direction,
            max_mutations=max_signal_mutations_per_signal,
        )
        mutation_records.extend(records)
        mutated_signals.extend(record["signal"] for record in records)
    return [*signals, *mutated_signals], mutation_records


def _initial_factor_candidates(
    signals: list[dict[str, Any]],
    client: LLMClient,
    *,
    max_candidates_per_signal: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for signal in signals:
        for candidate in generate_factor_candidates_with_llm(signal, client, max_candidates=max_candidates_per_signal, strict=False):
            validation = validate_factor_candidate(candidate)
            candidate["validation_status"] = "passed" if validation.ok else "failed"
            candidate["validation_message"] = validation.message
            if validation.ok:
                candidates.append(candidate)
    return candidates


def _prepare_seed_candidates(seed_candidates: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for candidate in seed_candidates or []:
        payload = dict(candidate)
        validation = validate_factor_candidate(payload)
        payload["validation_status"] = "passed" if validation.ok else "failed"
        payload["validation_message"] = validation.message
        payload.setdefault("created_by", "seed_factor_candidate")
        if validation.ok:
            candidates.append(payload)
    return candidates


def _render_initial_candidates(candidates: list[dict[str, Any]], output_dir: Path, *, fac_eval_config_path: str | Path = "configs/backtest.yaml") -> tuple[list[dict[str, Any]], list[str], str]:
    rendered_dir = output_dir / "initial" / "rendered"
    rendered_files: list[str] = []
    for candidate in candidates:
        factor_file = render_factor_file(candidate, rendered_dir)
        compile_result = py_compile_factor_file(factor_file)
        candidate["factor_file"] = str(factor_file)
        candidate["py_compile"] = {"ok": compile_result.returncode == 0, "returncode": compile_result.returncode, "stderr": compile_result.stderr}
        if compile_result.returncode == 0:
            rendered_files.append(str(factor_file))
    fac_eval_config = str(write_fac_eval_config(rendered_files, output_dir / "initial" / "fac_eval_config.yaml", config_path=fac_eval_config_path)) if rendered_files else ""
    return candidates, rendered_files, fac_eval_config


def run_batch_factor_iteration(
    signals_path: str | Path,
    *,
    output_dir: str | Path,
    client: LLMClient,
    generations: int = 1,
    max_candidates_per_signal: int = 2,
    max_signal_mutations_per_signal: int = 0,
    max_new_candidates: int = 20,
    metrics_path: str | Path | None = None,
    fac_eval_config_path: str | Path = "configs/backtest.yaml",
    run_fac_eval: bool = False,
    exploration_direction: str = "",
    seed_factor_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    signals = _load_signals(signals_path)
    factor_input_signals, signal_mutation_records = _mutate_signals(
        signals,
        client,
        max_signal_mutations_per_signal=max_signal_mutations_per_signal,
        exploration_direction=exploration_direction,
    )
    signal_mutations_path = root / "initial" / "signal_mutations.json"
    signal_mutations_path.parent.mkdir(parents=True, exist_ok=True)
    signal_mutations_path.write_text(json.dumps({"signal_mutations": signal_mutation_records, "signals_for_factor_generation": factor_input_signals}, ensure_ascii=False, indent=2), encoding="utf-8")
    seed_candidates = _prepare_seed_candidates(seed_factor_candidates)
    seed_candidates_path = root / "initial" / "seed_factor_candidates.json"
    seed_candidates_path.write_text(json.dumps({"factor_candidates": seed_candidates}, ensure_ascii=False, indent=2), encoding="utf-8")
    initial_candidates = [*seed_candidates, *_initial_factor_candidates(factor_input_signals, client, max_candidates_per_signal=max_candidates_per_signal)]
    initial_candidates, rendered_files, fac_eval_config = _render_initial_candidates(initial_candidates, root, fac_eval_config_path=fac_eval_config_path)
    candidates_path = root / "initial" / "factor_candidates.json"
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(json.dumps({"factor_candidates": initial_candidates}, ensure_ascii=False, indent=2), encoding="utf-8")

    iteration_summary = run_search_experiment(
        initial_candidates,
        output_dir=root / "iteration",
        generations=generations,
        run_fac_eval=run_fac_eval,
        metrics_path=metrics_path,
        fac_eval_config_path=fac_eval_config_path,
        max_new_candidates=max_new_candidates,
        client=client,
        exploration_direction=exploration_direction,
    )
    summary = {
        "status": "ok",
        "signal_count": len(signals),
        "signal_mutation_count": len(signal_mutation_records),
        "factor_input_signal_count": len(factor_input_signals),
        "signal_mutations": str(signal_mutations_path),
        "initial_candidate_count": len(initial_candidates),
        "seed_candidate_count": len(seed_candidates),
        "seed_candidates": str(seed_candidates_path),
        "initial_candidates": str(candidates_path),
        "initial_rendered_factor_files": rendered_files,
        "initial_fac_eval_config": fac_eval_config,
        "iteration": iteration_summary,
    }
    (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch-generate factors from many signals and run LLM-led mutation iterations.")
    parser.add_argument("--signals", required=True, help="Input signals JSON file: list or object with key 'signals'.")
    parser.add_argument("--output-dir", required=True, help="Output directory for initial factors and iteration artifacts.")
    parser.add_argument("--generations", type=int, default=1, help="Number of factor iteration generations.")
    parser.add_argument("--max-candidates-per-signal", type=int, default=2, help="Initial FactorCandidate count per signal.")
    parser.add_argument("--max-signal-mutations-per-signal", type=int, default=0, help="Optional Signal Mutation Agent outputs per parent signal before factor generation.")
    parser.add_argument("--max-new-candidates", type=int, default=20, help="Maximum LLM-mutated candidates per generation.")
    parser.add_argument("--metrics", default=None, help="Optional fac-eval metrics JSON/CSV/parquet.")
    parser.add_argument("--seed-factor-candidates", default="", help="Optional FactorCandidate JSON file to seed into the initial candidate pool.")
    parser.add_argument("--run-fac-eval", action="store_true", help="Optionally call fac-eval-demo during iteration.")
    parser.add_argument("--fac-eval-config-template", default="configs/backtest.yaml", help="Backtest/fac-eval template config used when writing fac-eval configs.")
    parser.add_argument("--exploration-direction", default="", help="Current exploration direction for the factor mutation agent.")
    parser.add_argument("--api-key", default=None, help="LLM API key. If omitted, environment variables from configs/llm.yaml are used.")
    parser.add_argument("--model", default=None, help="LLM model override.")
    args = parser.parse_args(argv)
    settings = settings_from_env(load_project_config().llm, api_key=args.api_key, model=args.model)
    client = LLMClient(settings)
    seed_factor_candidates = _load_factor_candidates(args.seed_factor_candidates) if args.seed_factor_candidates else []
    summary = run_batch_factor_iteration(
        args.signals,
        output_dir=args.output_dir,
        client=client,
        generations=args.generations,
        max_candidates_per_signal=args.max_candidates_per_signal,
        max_signal_mutations_per_signal=args.max_signal_mutations_per_signal,
        max_new_candidates=args.max_new_candidates,
        metrics_path=args.metrics,
        fac_eval_config_path=args.fac_eval_config_template,
        run_fac_eval=args.run_fac_eval,
        exploration_direction=args.exploration_direction,
        seed_factor_candidates=seed_factor_candidates,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())