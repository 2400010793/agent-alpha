from __future__ import annotations

import argparse
import hashlib
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
from agent_alpha.workflows.run_manifest import standard_run_paths, write_json, write_jsonl, write_run_manifest


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


def _signal_mutation_key(signal: dict[str, Any], max_mutations: int, exploration_direction: str) -> str:
    payload = {"signal": signal, "max_mutations": max_mutations, "exploration_direction": exploration_direction}
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _mutate_signals_resumable(
    signals: list[dict[str, Any]],
    client: LLMClient,
    *,
    max_signal_mutations_per_signal: int,
    exploration_direction: str,
    partial_path: Path,
    progress_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if max_signal_mutations_per_signal <= 0:
        return list(signals), []
    mutation_records: list[dict[str, Any]] = []
    completed_keys: set[str] = set()
    if partial_path.exists():
        for line in partial_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get("mutation_records"), list):
                continue
            records = [dict(item) for item in payload["mutation_records"] if isinstance(item, dict)]
            mutation_records.extend(records)
            if payload.get("signal_mutation_key"):
                completed_keys.add(str(payload["signal_mutation_key"]))
    if progress_path.exists():
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            completed_keys.update(str(item) for item in progress.get("completed_signal_keys", []) if item)
        except (AttributeError, json.JSONDecodeError):
            pass

    partial_path.parent.mkdir(parents=True, exist_ok=True)
    for signal in signals:
        key = _signal_mutation_key(signal, max_signal_mutations_per_signal, exploration_direction)
        if key in completed_keys:
            continue
        records = generate_signal_mutations(
            signal,
            client,
            exploration_direction=exploration_direction,
            max_mutations=max_signal_mutations_per_signal,
        )
        with partial_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"signal_mutation_key": key, "mutation_records": records}, ensure_ascii=False, sort_keys=True) + "\n")
        mutation_records.extend(records)
        completed_keys.add(key)
        write_json(
            progress_path,
            {
                "schema_version": "signal_mutation_progress_v1",
                "completed_signal_count": len(completed_keys),
                "completed_signal_keys": sorted(completed_keys),
                "requested_signal_count": len(signals),
                "partial_mutations": str(partial_path),
            },
        )
    mutated_signals = [record["signal"] for record in mutation_records if isinstance(record.get("signal"), dict)]
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


def _signal_generation_key(signal: dict[str, Any], max_candidates_per_signal: int) -> str:
    payload = {"signal": signal, "max_candidates_per_signal": max_candidates_per_signal}
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_partial_candidates(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    candidates: list[dict[str, Any]] = []
    completed_keys: set[str] = set()
    if not path.exists():
        return candidates, completed_keys
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if isinstance(record.get("candidates"), list):
            candidates.extend(dict(item) for item in record["candidates"] if isinstance(item, dict))
        elif isinstance(record.get("candidate"), dict):
            # Backward-compatible reader for the first partial format.
            candidates.append(dict(record["candidate"]))
        else:
            continue
        if record.get("signal_generation_key"):
            completed_keys.add(str(record["signal_generation_key"]))
    return candidates, completed_keys


def _initial_factor_candidates_resumable(
    signals: list[dict[str, Any]],
    client: LLMClient,
    *,
    max_candidates_per_signal: int,
    partial_path: Path,
    progress_path: Path,
) -> list[dict[str, Any]]:
    candidates, completed_keys = _load_partial_candidates(partial_path)
    progress: dict[str, Any] = {}
    if progress_path.exists():
        try:
            loaded = json.loads(progress_path.read_text(encoding="utf-8"))
            progress = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            progress = {}
    completed_keys.update(str(item) for item in progress.get("completed_signal_keys", []) if item)
    partial_path.parent.mkdir(parents=True, exist_ok=True)
    for signal in signals:
        generation_key = _signal_generation_key(signal, max_candidates_per_signal)
        if generation_key in completed_keys:
            continue
        generated = _initial_factor_candidates([signal], client, max_candidates_per_signal=max_candidates_per_signal)
        with partial_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "signal_generation_key": generation_key,
                        "source_signal_id": signal.get("signal_id", ""),
                        "candidates": generated,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
        candidates.extend(generated)
        completed_keys.add(generation_key)
        write_json(
            progress_path,
            {
                "schema_version": "factor_generation_progress_v1",
                "completed_signal_count": len(completed_keys),
                "completed_signal_keys": sorted(completed_keys),
                "requested_signal_count": len(signals),
                "partial_candidates": str(partial_path),
            },
        )
    if not progress_path.exists():
        write_json(
            progress_path,
            {
                "schema_version": "factor_generation_progress_v1",
                "completed_signal_count": len(completed_keys),
                "completed_signal_keys": sorted(completed_keys),
                "requested_signal_count": len(signals),
                "partial_candidates": str(partial_path),
            },
        )
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
    summarize_generation_memory: bool = False,
    memory_consolidation_records: int = 8,
    memory_consolidation_soft_chars: int = 24_000,
    memory_consolidation_hard_chars: int = 28_000,
    research_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    signals = _load_signals(signals_path)
    signal_mutations_partial_path = root / "initial" / "signal_mutations.partial.jsonl"
    signal_mutation_progress_path = root / "initial" / "signal_mutation_progress.json"
    factor_input_signals, signal_mutation_records = _mutate_signals_resumable(
        signals,
        client,
        max_signal_mutations_per_signal=max_signal_mutations_per_signal,
        exploration_direction=exploration_direction,
        partial_path=signal_mutations_partial_path,
        progress_path=signal_mutation_progress_path,
    )
    signal_mutations_path = root / "initial" / "signal_mutations.json"
    signal_mutations_path.parent.mkdir(parents=True, exist_ok=True)
    signal_mutations_path.write_text(json.dumps({"signal_mutations": signal_mutation_records, "signals_for_factor_generation": factor_input_signals}, ensure_ascii=False, indent=2), encoding="utf-8")
    seed_candidates = _prepare_seed_candidates(seed_factor_candidates)
    seed_candidates_path = root / "initial" / "seed_factor_candidates.json"
    seed_candidates_path.write_text(json.dumps({"factor_candidates": seed_candidates}, ensure_ascii=False, indent=2), encoding="utf-8")
    partial_candidates_path = root / "initial" / "factor_candidates.partial.jsonl"
    generation_progress_path = root / "initial" / "factor_generation_progress.json"
    generated_candidates = _initial_factor_candidates_resumable(
        factor_input_signals,
        client,
        max_candidates_per_signal=max_candidates_per_signal,
        partial_path=partial_candidates_path,
        progress_path=generation_progress_path,
    )
    initial_candidates = [*seed_candidates, *generated_candidates]
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
        source_signals=factor_input_signals,
        research_context=research_context,
        summarize_generation_memory=summarize_generation_memory,
        memory_consolidation_records=memory_consolidation_records,
        memory_consolidation_soft_chars=memory_consolidation_soft_chars,
        memory_consolidation_hard_chars=memory_consolidation_hard_chars,
    )
    summary = {
        "status": "ok",
        "signal_count": len(signals),
        "signal_mutation_count": len(signal_mutation_records),
        "factor_input_signal_count": len(factor_input_signals),
        "signal_mutations": str(signal_mutations_path),
        "signal_mutations_partial": str(signal_mutations_partial_path),
        "signal_mutation_progress": str(signal_mutation_progress_path),
        "initial_candidate_count": len(initial_candidates),
        "seed_candidate_count": len(seed_candidates),
        "seed_candidates": str(seed_candidates_path),
        "initial_candidates": str(candidates_path),
        "initial_candidates_partial": str(partial_candidates_path),
        "factor_generation_progress": str(generation_progress_path),
        "initial_rendered_factor_files": rendered_files,
        "initial_fac_eval_config": fac_eval_config,
        "iteration": iteration_summary,
    }
    paths = standard_run_paths(root)
    write_jsonl(paths["signals"], factor_input_signals)
    manifest = write_run_manifest(
        root,
        run_type="batch_factor_iteration",
        inputs={"signals_path": str(signals_path), "generations": generations, "research_context": research_context or {}},
        outputs=summary,
        summary={"signal_count": len(signals), "initial_candidate_count": len(initial_candidates)},
    )
    summary["manifest"] = str(paths["manifest"])
    summary["manifest_run_id"] = manifest["run_id"]
    write_json(root / "summary.json", summary)
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
