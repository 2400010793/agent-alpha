from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from agent_alpha.evaluation.fac_eval_result_reader import read_stock_level_metrics
from agent_alpha.evaluation.research_evaluator import evaluate_research_quality
from agent_alpha.evaluation.review_report_writer import write_review_report
from agent_alpha.factors.fac_eval_adapter import py_compile_factor_file, run_fac_eval_config, write_fac_eval_config
from agent_alpha.factors.factor_file_renderer import render_factor_file
from agent_alpha.factors.factor_identity import canonical_factor_key
from agent_alpha.library.alpha_library import append_alpha_record, build_alpha_record
from agent_alpha.llm.client import LLMClient
from agent_alpha.memory.evaluation_store import append_evaluation_record
from agent_alpha.memory.experiment_memory_writer import build_feedback_memory, write_feedback_memory
from agent_alpha.memory.memory_consolidation import MemoryConsolidationPolicy, consolidate_mutation_memory_dir
from agent_alpha.memory.memory_summary_agent import MemorySummaryAgent, MemorySummaryPaths
from agent_alpha.search.candidate_pool import CandidatePool
from agent_alpha.search.iterative_enhancer import enhance_candidates
from agent_alpha.search.lifecycle_policy import LineageState, lineage_id_for_candidate, update_lineage_state
from agent_alpha.search.mutation_controller import MutationPlan
from agent_alpha.workflows.run_manifest import safe_run_id, standard_run_paths, write_json, write_jsonl, write_run_manifest


def _load_candidates(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    candidates = payload.get("factor_candidates", payload.get("candidates", [])) if isinstance(payload, dict) else payload
    if not isinstance(candidates, list):
        raise ValueError("candidate input must be a list or an object with factor_candidates")
    return [dict(item) for item in candidates if isinstance(item, dict)]


def _metrics_by_factor(metrics_path: str | Path | None) -> dict[str, dict[str, Any]]:
    if not metrics_path:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in read_stock_level_metrics(metrics_path):
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


def _factor_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("factor_id") or candidate.get("name") or "")


def _validate_unique_factor_ids(candidates: list[dict[str, Any]]) -> None:
    definitions: dict[str, str] = {}
    for candidate in candidates:
        factor_id = _factor_id(candidate)
        if not factor_id:
            raise ValueError("factor candidate must have a non-empty factor_id or name")
        definition = canonical_factor_key(candidate)
        previous = definitions.get(factor_id)
        if previous is not None and previous != definition:
            raise ValueError(f"factor_id collision maps to different definitions: {factor_id}")
        definitions[factor_id] = definition


def _source_signal_lookup(source_signals: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    return {str(signal.get("signal_id")): signal for signal in source_signals or [] if signal.get("signal_id")}


def _memory_agent(paths: dict[str, Path]) -> MemorySummaryAgent:
    return MemorySummaryAgent(
        MemorySummaryPaths(
            specialist_root=paths["specialist_memory_dir"],
            function_memory_path=paths["function_memory"],
            transfer_memory_path=paths["transfer_memory"],
            mutation_arm_memory_path=paths["mutation_arm_memory"],
        )
    )


def _write_child_outcome_memory(
    memory_agent: MemorySummaryAgent,
    candidate: dict[str, Any],
    review: dict[str, Any],
    candidates_by_id: dict[str, dict[str, Any]],
    reviews_by_id: dict[str, dict[str, Any]],
) -> bool:
    parent_ids = candidate.get("parent_ids") if isinstance(candidate.get("parent_ids"), list) else []
    mutation_focus = str(candidate.get("mutation_type") or "")
    agent_name = str(candidate.get("specialist_agent_name") or "")
    if not parent_ids or not mutation_focus or not agent_name:
        return False
    parent_id = str(parent_ids[0])
    parent = candidates_by_id.get(parent_id)
    if parent is None:
        return False
    plan = MutationPlan(
        parent_candidate=parent,
        mutation_focus=mutation_focus,
        agent_name=agent_name,
        reason=str(candidate.get("financial_reason") or candidate.get("mutated_idea") or "reviewed mutation outcome"),
    )
    memory_agent.write_mutation_memories(plan, candidate, child_review=review, parent_review=reviews_by_id.get(parent_id))
    return True


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
    source_signals: list[dict[str, Any]] | None = None,
    research_context: dict[str, Any] | None = None,
    summarize_generation_memory: bool = False,
    memory_consolidation_records: int = 8,
    memory_consolidation_soft_chars: int = 24_000,
    memory_consolidation_hard_chars: int = 28_000,
) -> dict[str, Any]:
    """Run one isolated, auditable factor search experiment."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths = standard_run_paths(root)
    for directory_key in ("rendered", "reports", "specialist_memory_dir"):
        paths[directory_key].mkdir(parents=True, exist_ok=True)

    context = dict(research_context or {})
    run_scope = safe_run_id(str(context.get("research_run_id") or context.get("graph_id") or root.name))
    signal_lookup = _source_signal_lookup(source_signals)
    candidate_pool = CandidatePool()
    memory_agent = _memory_agent(paths)
    current_candidates = [dict(candidate) for candidate in candidates]
    _validate_unique_factor_ids(current_candidates)
    candidates_by_id = {_factor_id(candidate): candidate for candidate in current_candidates}
    reviews_by_id: dict[str, dict[str, Any]] = {}
    lineage_states: dict[str, LineageState] = {}
    all_candidates: list[dict[str, Any]] = []
    all_reviews: list[dict[str, Any]] = []
    all_feedback: list[dict[str, Any]] = []
    all_frontier: list[dict[str, Any]] = []
    selection_trace: list[dict[str, Any]] = []
    rendered_files: list[str] = []
    metrics_lookup = _metrics_by_factor(metrics_path)

    max_generations = max(1, generations)
    for generation in range(max_generations):
        generation_dir = root / f"generation_{generation}"
        rendered_dir = paths["rendered"] / f"generation_{generation}"
        reports_dir = paths["reports"] / f"generation_{generation}"
        rendered_dir.mkdir(parents=True, exist_ok=True)
        reports_dir.mkdir(parents=True, exist_ok=True)
        generation_rendered: list[str] = []
        generation_candidates: list[dict[str, Any]] = []
        _validate_unique_factor_ids(current_candidates)
        pool_records: dict[str, str] = {}

        for input_candidate in current_candidates:
            candidate = dict(input_candidate)
            candidate.setdefault("research_run_id", context.get("research_run_id", run_scope))
            for key in ("graph_id", "hypothesis_id", "evidence_ids"):
                if key in context and key not in candidate:
                    candidate[key] = context[key]
            candidate_id = _factor_id(candidate)
            candidates_by_id[candidate_id] = candidate
            pool_record = candidate_pool.add(
                candidate,
                parent_ids=[str(item) for item in candidate.get("parent_ids", [])],
                generation=generation,
                status="created",
            )
            pool_records[candidate_id] = pool_record.candidate_id
            try:
                factor_file = render_factor_file(candidate, rendered_dir)
                compile_proc = py_compile_factor_file(factor_file)
                compile_result = {"ok": compile_proc.returncode == 0, "returncode": compile_proc.returncode, "stderr": compile_proc.stderr}
                candidate_pool.update_status(pool_record.candidate_id, "compiled" if compile_result["ok"] else "rejected")
                candidate["factor_file"] = str(factor_file)
                candidate["compile_result"] = compile_result
                if compile_result["ok"]:
                    generation_rendered.append(str(factor_file))
                    rendered_files.append(str(factor_file))
            except Exception as exc:
                candidate["compile_result"] = {"ok": False, "message": str(exc)}
                candidate_pool.update_status(pool_record.candidate_id, "rejected")
            generation_candidates.append(candidate)
            all_candidates.append(candidate)

        fac_eval_config = ""
        fac_eval_result = None
        fac_eval_metrics_path = ""
        generation_metrics_lookup: dict[str, dict[str, Any]] = {}
        if generation_rendered:
            fac_eval_config = str(write_fac_eval_config(generation_rendered, generation_dir / "fac_eval_config.yaml", config_path=fac_eval_config_path))
            if run_fac_eval:
                eval_run_id = safe_run_id(f"{run_scope}_generation_{generation}")
                proc = run_fac_eval_config(fac_eval_config, run_id=eval_run_id)
                fac_eval_result = {"ok": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
                inferred_metrics_path = _fac_eval_stock_level_path(fac_eval_config, eval_run_id)
                if inferred_metrics_path.exists():
                    fac_eval_metrics_path = str(inferred_metrics_path)
                    generation_metrics_lookup = _metrics_by_factor(inferred_metrics_path)

        combined_metrics_lookup = _merge_metric_lookups(metrics_lookup, generation_metrics_lookup)
        generation_reviews: list[dict[str, Any]] = []
        generation_feedback: list[dict[str, Any]] = []
        for candidate in generation_candidates:
            candidate_id = _factor_id(candidate)
            metrics = combined_metrics_lookup.get(candidate_id, {})
            review = evaluate_research_quality(
                candidate,
                metrics,
                compile_result=candidate.get("compile_result"),
                render_result={"path": candidate.get("factor_file", "")},
                source_signal=signal_lookup.get(str(candidate.get("source_signal_id") or "")),
            )
            reviews_by_id[candidate_id] = review
            generation_reviews.append(review)
            all_reviews.append(review)
            evaluation_record = review.get("evaluation_record", review)
            append_evaluation_record(evaluation_record, path=root / "evaluation_records.jsonl")
            feedback = build_feedback_memory(review, candidate)
            generation_feedback.append(feedback)
            all_feedback.append(feedback)
            pool_record_id = pool_records.get(candidate_id, "")
            if review.get("decision") == "accept":
                try:
                    append_alpha_record(build_alpha_record(candidate, review, metrics), path=root / "alpha_library.jsonl")
                    if pool_record_id:
                        candidate_pool.update_status(pool_record_id, "accepted")
                except ValueError:
                    if pool_record_id:
                        candidate_pool.update_status(pool_record_id, "evaluated")
            elif pool_record_id:
                candidate_pool.update_status(pool_record_id, "evaluated" if review.get("decision") == "revise" else "rejected")
            write_review_report(reports_dir / f"{candidate_id}.md", review)

        for candidate in generation_candidates:
            candidate_id = _factor_id(candidate)
            _write_child_outcome_memory(memory_agent, candidate, reviews_by_id[candidate_id], candidates_by_id, reviews_by_id)

        reviews_by_lineage: dict[str, list[dict[str, Any]]] = {}
        for candidate in generation_candidates:
            reviews_by_lineage.setdefault(lineage_id_for_candidate(candidate), []).append(reviews_by_id[_factor_id(candidate)])
        for lineage_id, reviews in reviews_by_lineage.items():
            state = lineage_states.setdefault(lineage_id, LineageState(lineage_id=lineage_id))
            update_lineage_state(state, reviews)

        if summarize_generation_memory and client is not None:
            memory_agent.write_llm_summaries(
                [{"candidate": candidate, "review": reviews_by_id[_factor_id(candidate)]} for candidate in generation_candidates],
                client,
            )
        consolidation = consolidate_mutation_memory_dir(
            root / "memory",
            policy=MemoryConsolidationPolicy(
                min_records=max(1, memory_consolidation_records),
                soft_chars=max(1, memory_consolidation_soft_chars),
                hard_chars=max(1, memory_consolidation_hard_chars),
            ),
        )

        generation_frontier = [dict(candidate) for candidate in generation_candidates]
        all_frontier = generation_frontier
        next_candidates: list[dict[str, Any]] = []
        if generation < max_generations - 1:
            next_candidates = enhance_candidates(
                current_candidates,
                all_feedback,
                max_new_candidates=max_new_candidates,
                client=client,
                exploration_direction=exploration_direction,
                lineage_states={key: asdict(value) for key, value in lineage_states.items()},
            )
            for child in next_candidates:
                selection_trace.append(
                    {
                        "generation": generation,
                        "child_factor_id": _factor_id(child),
                        "parent_ids": list(child.get("parent_ids") or []),
                        "mutation_type": child.get("mutation_type", ""),
                        "specialist_agent_name": child.get("specialist_agent_name", ""),
                    }
                )

        write_feedback_memory(root / "feedback_memory.jsonl", all_feedback)
        write_jsonl(paths["candidates"], all_candidates)
        write_jsonl(paths["frontier"], all_frontier)
        write_jsonl(paths["evaluations"], [review.get("evaluation_record", review) for review in all_reviews])
        write_jsonl(paths["selection_trace"], selection_trace)
        write_json(paths["lineage_states"], {key: asdict(value) for key, value in lineage_states.items()})
        write_json(
            generation_dir / "summary.json",
            {
                "generation": generation,
                "input_count": len(current_candidates),
                "rendered_files": generation_rendered,
                "fac_eval_config": fac_eval_config,
                "fac_eval_result": fac_eval_result,
                "fac_eval_metrics_path": fac_eval_metrics_path,
                "review_count": len(generation_candidates),
                "frontier_count": len(generation_frontier),
                "next_candidate_count": len(next_candidates),
                "memory_consolidation": consolidation,
            },
        )
        current_candidates = next_candidates
        if not current_candidates:
            break

    pool_path = root / "candidate_pool.jsonl"
    candidate_pool.to_jsonl(pool_path)
    summary = {
        "status": "ok",
        "run_id": run_scope,
        "rendered_factor_files": rendered_files,
        "review_count": len(all_reviews),
        "feedback_count": len(all_feedback),
        "candidate_pool": str(pool_path),
        "candidates": str(paths["candidates"]),
        "frontier": str(paths["frontier"]),
        "lineage_states": str(paths["lineage_states"]),
        "selection_trace": str(paths["selection_trace"]),
        "feedback_memory": str(root / "feedback_memory.jsonl"),
        "evaluation_records": str(root / "evaluation_records.jsonl"),
        "evaluations": str(paths["evaluations"]),
        "alpha_library": str(root / "alpha_library.jsonl"),
    }
    manifest = write_run_manifest(
        root,
        run_type="factor_search_experiment",
        inputs={"candidate_count": len(candidates), "generations": max_generations, "metrics_path": str(metrics_path or ""), "research_context": context},
        outputs=summary,
        summary={"review_count": len(all_reviews), "frontier_count": len(all_frontier)},
    )
    summary["manifest"] = str(paths["manifest"])
    summary["manifest_run_id"] = manifest["run_id"]
    write_json(root / "summary.json", summary)
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
    **kwargs: Any,
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
        **kwargs,
    )
