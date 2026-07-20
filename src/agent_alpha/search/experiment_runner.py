from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from agent_alpha.evaluation.fac_eval_result_reader import read_stock_level_metrics
from agent_alpha.evaluation.research_evaluator import evaluate_research_quality
from agent_alpha.evaluation.review_report_writer import write_review_report
from agent_alpha.factors.fac_eval_adapter import py_compile_factor_file, run_fac_eval_config, write_fac_eval_config
from agent_alpha.factors.factor_file_renderer import render_factor_file
from agent_alpha.library.alpha_library import append_alpha_record
from agent_alpha.llm.client import LLMClient
from agent_alpha.memory.evaluation_store import append_evaluation_record
from agent_alpha.memory.experiment_memory_writer import build_feedback_memory, write_feedback_memory
from agent_alpha.search.candidate_pool import CandidatePool
from agent_alpha.search.iterative_enhancer import enhance_candidates


def _load_candidates(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        candidates = payload.get("factor_candidates", payload.get("candidates", []))
    else:
        candidates = payload
    if not isinstance(candidates, list):
        raise ValueError("candidate input must be a list or an object with factor_candidates")
    return [dict(item) for item in candidates if isinstance(item, dict)]


def _metrics_by_factor(metrics_path: str | Path | None) -> dict[str, dict[str, Any]]:
    if not metrics_path:
        return {}
    rows = read_stock_level_metrics(metrics_path)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        factor_id = str(row.get("factor_id") or row.get("factor_name") or row.get("name") or "")
        if factor_id:
            out[factor_id] = row
    return out


def _fac_eval_stock_level_path(config_path: str | Path, run_id: str) -> Path:
    config_file = Path(config_path)
    payload = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    output_dir = Path(str(payload.get("output_dir", "outputs"))).expanduser()
    if not output_dir.is_absolute():
        output_dir = config_file.parent / output_dir
    return output_dir / "factor_eval" / f"run_id={run_id}" / "stock_level.parquet"


def _merge_metric_lookups(*lookups: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for lookup in lookups:
        merged.update(lookup)
    return merged


def run_search_experiment(
    candidates: list[dict[str, Any]],
    *,
    output_dir: str | Path,
    generations: int = 1,
    run_fac_eval: bool = False,
    metrics_path: str | Path | None = None,
    fac_eval_config_path: str | Path = "configs/backtest.yaml",
    max_new_candidates: int = 20,
    client: LLMClient | None = None,
    exploration_direction: str = "",
) -> dict[str, Any]:
    """Run deterministic iteration orchestration without implementing underlying algorithms."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    candidate_pool = CandidatePool()
    current_candidates = list(candidates)
    all_reviews: list[dict[str, Any]] = []
    all_feedback: list[dict[str, Any]] = []
    rendered_files: list[str] = []
    compile_results: dict[str, dict[str, Any]] = {}
    metrics_lookup = _metrics_by_factor(metrics_path)

    max_generations = max(1, generations)
    for generation in range(max_generations):
        generation_dir = root / f"generation_{generation}"
        rendered_dir = generation_dir / "rendered"
        rendered_dir.mkdir(parents=True, exist_ok=True)
        generation_rendered: list[str] = []
        generation_candidates: list[dict[str, Any]] = []
        pool_records: dict[str, str] = {}
        for candidate in current_candidates:
            pool_record = candidate_pool.add(candidate, generation=generation, status="created")
            candidate_key = str(candidate.get("factor_id") or candidate.get("name"))
            pool_records[candidate_key] = pool_record.candidate_id
            try:
                factor_file = render_factor_file(candidate, rendered_dir)
                compile_proc = py_compile_factor_file(factor_file)
                compile_result = {"ok": compile_proc.returncode == 0, "returncode": compile_proc.returncode, "stderr": compile_proc.stderr}
                compile_results[str(candidate.get("factor_id") or candidate.get("name"))] = compile_result
                candidate_pool.update_status(pool_record.candidate_id, "compiled" if compile_result["ok"] else "rejected")
                candidate["factor_file"] = str(factor_file)
                candidate["compile_result"] = compile_result
                if compile_result["ok"]:
                    generation_rendered.append(str(factor_file))
                    rendered_files.append(str(factor_file))
            except Exception as exc:
                compile_result = {"ok": False, "message": str(exc)}
                candidate["compile_result"] = compile_result
                candidate_pool.update_status(pool_record.candidate_id, "rejected")
            generation_candidates.append(candidate)

        fac_eval_config = ""
        fac_eval_result = None
        fac_eval_metrics_path = ""
        generation_metrics_lookup: dict[str, dict[str, Any]] = {}
        if generation_rendered:
            fac_eval_config = str(write_fac_eval_config(generation_rendered, generation_dir / "fac_eval_config.yaml", config_path=fac_eval_config_path))
            if run_fac_eval:
                run_id = f"agent_alpha_gen_{generation}"
                proc = run_fac_eval_config(fac_eval_config, run_id=run_id)
                fac_eval_result = {"ok": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
                inferred_metrics_path = _fac_eval_stock_level_path(fac_eval_config, run_id)
                if inferred_metrics_path.exists():
                    fac_eval_metrics_path = str(inferred_metrics_path)
                    generation_metrics_lookup = _metrics_by_factor(inferred_metrics_path)

        combined_metrics_lookup = _merge_metric_lookups(metrics_lookup, generation_metrics_lookup)

        for candidate in generation_candidates:
            candidate_key = str(candidate.get("factor_id") or candidate.get("name"))
            pool_record_id = pool_records.get(candidate_key, "")

            metrics = combined_metrics_lookup.get(candidate_key, {})
            review = evaluate_research_quality(candidate, metrics, compile_result=candidate.get("compile_result"), render_result={"path": candidate.get("factor_file", "")})
            all_reviews.append(review)
            append_evaluation_record(review.get("evaluation_record", review), path=root / "evaluation_records.jsonl")
            feedback = build_feedback_memory(review, candidate)
            all_feedback.append(feedback)
            if review.get("decision") == "accept":
                try:
                    append_alpha_record({**review, "metrics": metrics}, path=root / "alpha_library.jsonl")
                    if pool_record_id:
                        candidate_pool.update_status(pool_record_id, "accepted")
                except ValueError:
                    pass
            write_review_report(generation_dir / "reviews" / f"{candidate.get('factor_id') or candidate.get('name')}.md", review)

        write_feedback_memory(root / "feedback_memory.jsonl", all_feedback)
        next_candidates = []
        if generation < max_generations - 1:
            next_candidates = enhance_candidates(
                current_candidates,
                all_feedback,
                max_new_candidates=max_new_candidates,
                client=client,
                exploration_direction=exploration_direction,
            )
        (generation_dir / "summary.json").write_text(
            json.dumps(
                {
                    "generation": generation,
                    "input_count": len(current_candidates),
                    "rendered_files": generation_rendered,
                    "fac_eval_config": fac_eval_config,
                    "fac_eval_result": fac_eval_result,
                    "fac_eval_metrics_path": fac_eval_metrics_path,
                    "review_count": len(generation_candidates),
                    "next_candidate_count": len(next_candidates),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        current_candidates = next_candidates
        if not current_candidates:
            break

    pool_path = root / "candidate_pool.jsonl"
    candidate_pool.to_jsonl(pool_path)
    summary = {
        "status": "ok",
        "rendered_factor_files": rendered_files,
        "review_count": len(all_reviews),
        "feedback_count": len(all_feedback),
        "candidate_pool": str(pool_path),
        "feedback_memory": str(root / "feedback_memory.jsonl"),
        "evaluation_records": str(root / "evaluation_records.jsonl"),
        "alpha_library": str(root / "alpha_library.jsonl"),
    }
    (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def run_search_experiment_from_file(
    candidates_path: str | Path,
    *,
    output_dir: str | Path,
    generations: int = 1,
    run_fac_eval: bool = False,
    metrics_path: str | Path | None = None,
    fac_eval_config_path: str | Path = "configs/backtest.yaml",
    max_new_candidates: int = 20,
    client: LLMClient | None = None,
    exploration_direction: str = "",
) -> dict[str, Any]:
    return run_search_experiment(
        _load_candidates(candidates_path),
        output_dir=output_dir,
        generations=generations,
        run_fac_eval=run_fac_eval,
        metrics_path=metrics_path,
        fac_eval_config_path=fac_eval_config_path,
        max_new_candidates=max_new_candidates,
        client=client,
        exploration_direction=exploration_direction,
    )