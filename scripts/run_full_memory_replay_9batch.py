from __future__ import annotations

import argparse
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_alpha.config import load_project_config
from agent_alpha.llm.client import LLMClient, LLMSettings, settings_from_env
from agent_alpha.memory.memory_consolidation import MemoryConsolidationPolicy, consolidate_mutation_memory_dir
from agent_alpha.memory.memory_summary_agent import MemorySummaryAgent, MemorySummaryPaths
from agent_alpha.search.mutation_controller import MUTATION_AGENT_BY_FOCUS, MutationPlan


"""
Replay existing mutation artifacts into memory in 9 small API-assisted batches.

This script is designed to avoid prompt/memory blowups while supporting two safe
execution styles:

1. One batch per scheduled call:
    */30 * * * * cd /home/gaozh/agent_alpha && PYTHONPATH=src python scripts/run_full_memory_replay_9batch.py --output-dir outputs/full_memory_replay_9batch_api

2. One process, three keys at once, three waves total:
    PYTHONPATH=src python scripts/run_full_memory_replay_9batch.py --run-waves --output-dir outputs/full_memory_replay_9batch_api

Key policy:
- The script resolves up to 3 API keys from configs/llm.yaml/env.
- Batch i uses key i % key_count.
- In --run-waves mode, batches 1/2/3 run concurrently on keys 1/2/3,
  then the script waits 30 minutes before batches 4/5/6, then another
  30 minutes before batches 7/8/9. Total wall time is about 90 minutes.
- A state file prevents rerunning completed batches by accident.

It does not run reading and does not generate new factors. It replays existing
mutation candidates, fakes API-like reviews, writes rule-based mutation memory,
then calls the LLM memory summarizer once per batch.
"""


TARGET_COUNTS = {
    "state_condition_mutation": 24,
    "event_definition_mutation": 20,
    "normalization_robustness_mutation": 20,
    "time_structure_mutation": 8,
    "refinement_simplification": 8,
}

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "full_memory_replay_9batch_api"
DEFAULT_BATCH_COUNT = 9


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def candidate_list_from_payload(payload: Any) -> list[dict[str, Any]]:
    candidates = payload.get("factor_candidates", payload.get("candidates", [])) if isinstance(payload, dict) else payload
    if not isinstance(candidates, list):
        return []
    return [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]


def factor_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("factor_id") or candidate.get("name") or "")


def resolve_keys(config: dict[str, Any], *, max_keys: int = 3) -> list[str]:
    keys: list[str] = []
    for entry in config.get("api_key_envs", []):
        text = str(entry)
        if "=" in text:
            _, value = text.split("=", 1)
            if value.strip():
                keys.append(value.strip())
        else:
            value = os.environ.get(text, "").strip()
            if value:
                keys.append(value)
        if len(keys) >= max_keys:
            break
    if not keys:
        keys.append(settings_from_env(config).api_key)
    return keys[:max_keys]


def settings_for_key(config: dict[str, Any], key: str) -> LLMSettings:
    return settings_from_env(config, api_key=key)


def is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return "429" in text or "too many" in text or "rate limit" in text or "ratelimit" in text


def candidate_files() -> list[Path]:
    roots = [PROJECT_ROOT / "outputs"]
    names: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        names.extend(sorted(root.rglob("*candidate*.json")))
        names.extend(sorted(root.rglob("*candidates.json")))
    seen: set[Path] = set()
    out: list[Path] = []
    for path in names:
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def collect_available_records() -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    by_type: dict[str, list[dict[str, Any]]] = {key: [] for key in TARGET_COUNTS}
    parent_lookup: dict[str, dict[str, Any]] = {}
    seen_occurrence: set[tuple[str, str, str]] = set()
    for path in candidate_files():
        try:
            candidates = candidate_list_from_payload(load_json(path))
        except Exception:
            continue
        for candidate in candidates:
            fid = factor_id(candidate)
            if fid:
                parent_lookup.setdefault(fid, dict(candidate))
            mutation_type = str(candidate.get("mutation_type") or "")
            if mutation_type not in TARGET_COUNTS:
                continue
            occurrence_key = (str(path), mutation_type, fid)
            if occurrence_key in seen_occurrence:
                continue
            seen_occurrence.add(occurrence_key)
            payload = dict(candidate)
            payload["_source_file"] = str(path.relative_to(PROJECT_ROOT)) if path.is_relative_to(PROJECT_ROOT) else str(path)
            by_type[mutation_type].append(payload)
    return by_type, parent_lookup


def build_replay_records(*, allow_repeat_fill: bool = True, unique_only: bool = False) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, int]]:
    by_type, parent_lookup = collect_available_records()
    selected: list[dict[str, Any]] = []
    available_counts = {key: len(value) for key, value in by_type.items()}
    for mutation_type, configured_target in TARGET_COUNTS.items():
        records = by_type.get(mutation_type, [])
        target = len(records) if unique_only else configured_target
        if target <= 0:
            continue
        if len(records) >= target:
            chosen = records[:target]
        elif allow_repeat_fill and records:
            chosen = []
            for index in range(target):
                payload = dict(records[index % len(records)])
                payload["_replay_repeat_index"] = index // len(records)
                chosen.append(payload)
        else:
            raise RuntimeError(f"not enough records for {mutation_type}: need={target}, available={len(records)}")
        selected.extend(chosen)
    selected.sort(key=lambda item: (str(item.get("mutation_type")), str(item.get("factor_id") or item.get("name")), int(item.get("_replay_repeat_index", 0))))
    return selected, parent_lookup, available_counts


def chunk_records(records: list[dict[str, Any]], batch_count: int) -> list[list[dict[str, Any]]]:
    chunk_size = max(1, math.ceil(len(records) / batch_count))
    return [records[index : index + chunk_size] for index in range(0, len(records), chunk_size)]


def load_state(path: Path, batch_count: int) -> dict[str, Any]:
    if path.exists():
        payload = load_json(path)
        if isinstance(payload, dict):
            return payload
    return {"created_at": utc_now_iso(), "next_batch": 0, "completed_batches": [], "batch_count": batch_count, "keys": []}


def save_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now_iso()
    write_json(path, state)


def key_state(state: dict[str, Any], index: int) -> dict[str, Any]:
    keys = state.setdefault("keys", [])
    while len(keys) <= index:
        keys.append({"key_index": len(keys), "next_available_ts": 0.0, "success_count": 0, "rate_limit_count": 0, "error_count": 0})
    return keys[index]


def wait_or_skip_key(state: dict[str, Any], key_index: int, *, wait_for_key: bool, state_path: Path) -> bool:
    item = key_state(state, key_index)
    now = time.time()
    next_available = float(item.get("next_available_ts", 0.0))
    if next_available <= now:
        return True
    sleep_sec = next_available - now
    message = {"event": "key_cooling_down", "key_index": key_index + 1, "sleep_sec": round(sleep_sec, 1), "time": utc_now_iso()}
    print(json.dumps(message, ensure_ascii=False), flush=True)
    if not wait_for_key:
        save_state(state_path, state)
        return False
    time.sleep(max(1.0, sleep_sec))
    return True


def fallback_parent(child: dict[str, Any]) -> dict[str, Any]:
    parent_id = str((child.get("parent_ids") or [""])[0] or "")
    return {
        "factor_id": parent_id or f"fake_parent_for_{factor_id(child)}",
        "name": parent_id or f"fake_parent_for_{factor_id(child)}",
        "prefix_expression": child.get("prefix_expression"),
        "fields": list(child.get("fields") or []),
        "windows": list(child.get("windows") or []),
        "mechanism_tags": list(child.get("mechanism_tags") or []),
        "economic_rationale": f"Reconstructed fake parent for replayed mutation {factor_id(child)}.",
    }


def fake_decision(index: int, mutation_type: str) -> tuple[str, list[str]]:
    if mutation_type in {"state_condition_mutation", "time_structure_mutation"} and index % 3 != 1:
        return "accept", []
    if index % 11 == 0:
        return "reject", ["compile_failed"]
    return "revise", ["weak_rankic"]


def score_pair(index: int, mutation_type: str, decision: str) -> tuple[float, float]:
    base = 0.024 + (index % 7) * 0.003
    uplift_by_type = {
        "state_condition_mutation": 0.020,
        "event_definition_mutation": 0.012,
        "normalization_robustness_mutation": 0.014,
        "time_structure_mutation": 0.017,
        "refinement_simplification": 0.011,
    }
    uplift = uplift_by_type.get(mutation_type, 0.01)
    if decision == "accept":
        uplift += 0.012
    if decision == "reject":
        uplift = -0.005
    return round(base, 6), round(base + uplift, 6)


def memory_counts(output_dir: Path) -> dict[str, int]:
    memory_root = output_dir / "mutation_memory"
    if not memory_root.exists():
        return {}
    counts: dict[str, int] = {}
    for path in sorted(memory_root.rglob("*.jsonl")):
        counts[str(path.relative_to(output_dir))] = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return counts


def run_one_batch(
    *,
    batch_index: int,
    batches: list[list[dict[str, Any]]],
    parent_lookup: dict[str, dict[str, Any]],
    client: LLMClient,
    output_dir: Path,
) -> dict[str, Any]:
    memory_root = output_dir / "mutation_memory"
    paths = MemorySummaryPaths(
        specialist_root=memory_root / "specialist_agents",
        function_memory_path=memory_root / "function_memory.jsonl",
        transfer_memory_path=memory_root / "transfer_memory.jsonl",
        mutation_arm_memory_path=memory_root / "mutation_arm_memory.jsonl",
    )
    agent = MemorySummaryAgent(paths)
    batch = batches[batch_index]
    feedback_for_llm: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    offset = sum(len(item) for item in batches[:batch_index])
    for local_index, child in enumerate(batch):
        global_index = offset + local_index
        mutation_type = str(child.get("mutation_type") or "")
        agent_name = MUTATION_AGENT_BY_FOCUS[mutation_type]
        parent_id = str((child.get("parent_ids") or [""])[0] or "")
        parent = dict(parent_lookup.get(parent_id) or fallback_parent(child))
        decision, failure_modes = fake_decision(global_index, mutation_type)
        parent_score, child_score = score_pair(global_index, mutation_type, decision)
        summary = str(child.get("economic_rationale") or child.get("mutated_idea") or f"Replayed {mutation_type} mutation.")
        child = dict(child)
        child["specialist_agent_name"] = agent_name
        child["mutated_idea"] = summary
        plan = MutationPlan(
            parent_candidate=parent,
            mutation_focus=mutation_type,
            agent_name=agent_name,
            reason=f"Full replay batch {batch_index + 1}: classify existing mutation as {agent_name}.",
        )
        parent_review = {"decision": "revise", "metrics": {"daily_rankic": parent_score, "finite_ratio": 0.96, "zero_ratio": 0.18, "n_obs": 10000}}
        child_review = {
            "decision": decision,
            "metrics": {"daily_rankic": child_score, "finite_ratio": 0.97, "zero_ratio": 0.16, "n_obs": 10000},
            "failure_modes": failure_modes,
            "required_revisions": [] if decision == "accept" else ["Use specialist memory to refine mechanism, fields, or horizon."],
            "api_report_source": "fake_full_replay_9batch_v1",
        }
        memory_records = agent.write_mutation_memories(plan, child, child_review=child_review, parent_review=parent_review)
        row = {
            "batch": batch_index + 1,
            "assigned_specialist_agent": agent_name,
            "mutation_type": mutation_type,
            "source_file": child.get("_source_file"),
            "repeat_index": child.get("_replay_repeat_index", 0),
            "parent_factor_id": parent.get("factor_id") or parent.get("name"),
            "child_factor_id": factor_id(child),
            "parent_score": parent_score,
            "child_score": child_score,
            "delta_score": round(child_score - parent_score, 6),
            "decision": decision,
            "failure_modes": failure_modes,
            "summary": summary,
            "written_memory_ids": {key: value.get("memory_id") or value.get("event_id") for key, value in memory_records.items()},
        }
        rows.append(row)
        feedback_for_llm.append(
            {
                "factor_id": row["child_factor_id"],
                "label": {"accept": "GOOD", "reject": "BAD", "revise": "REVISE"}[decision],
                "mutation_type": mutation_type,
                "agent_name": agent_name,
                "summary": summary,
                "failure_modes": failure_modes,
                "metrics": child_review["metrics"],
                "fields": child.get("fields", []),
                "windows": child.get("windows", []),
            }
        )
    llm_written = agent.write_llm_summaries(feedback_for_llm, client, max_records=len(feedback_for_llm))
    batch_report = {
        "batch": batch_index + 1,
        "input_records": len(batch),
        "llm_function_memory_written": len(llm_written.get("function_memory", [])),
        "llm_transfer_memory_written": len(llm_written.get("transfer_memory", [])),
        "rows": rows,
        "memory_counts_after_batch": memory_counts(output_dir),
    }
    write_json(output_dir / f"batch_{batch_index + 1:02d}_summary.json", batch_report)
    return batch_report


def run_wave(
    *,
    wave_indices: list[int],
    batches: list[list[dict[str, Any]]],
    parent_lookup: dict[str, dict[str, Any]],
    config: dict[str, Any],
    keys: list[str],
    output_dir: Path,
    state: dict[str, Any],
    state_path: Path,
    key_cooldown_sec: int,
) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(wave_indices)) as executor:
        futures = {}
        for batch_index in wave_indices:
            key_index = batch_index % len(keys)
            client = LLMClient(settings_for_key(config, keys[key_index]))
            futures[
                executor.submit(
                    run_one_batch,
                    batch_index=batch_index,
                    batches=batches,
                    parent_lookup=parent_lookup,
                    client=client,
                    output_dir=output_dir,
                )
            ] = (batch_index, key_index)
        for future in as_completed(futures):
            batch_index, key_index = futures[future]
            item = key_state(state, key_index)
            now = time.time()
            try:
                report = future.result()
            except Exception as exc:  # noqa: BLE001 - persist retry state for scheduled jobs.
                item["last_error"] = str(exc)[:500]
                item["last_used_ts"] = now
                item["next_available_ts"] = now + key_cooldown_sec
                item["error_count"] = int(item.get("error_count", 0)) + 1
                save_state(state_path, state)
                raise
            item["success_count"] = int(item.get("success_count", 0)) + 1
            item["last_used_ts"] = now
            item["next_available_ts"] = now + key_cooldown_sec
            completed = set(int(value) for value in state.get("completed_batches", []))
            completed.add(batch_index)
            state["completed_batches"] = sorted(completed)
            state["next_batch"] = min((index for index in range(len(batches)) if index not in completed), default=len(batches))
            save_state(state_path, state)
            reports.append(report)
            print(json.dumps({"event": "batch_done", "batch": batch_index + 1, "key_index": key_index + 1, "input_records": len(batches[batch_index])}, ensure_ascii=False), flush=True)
    return sorted(reports, key=lambda item: int(item.get("batch", 0)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay all mutation records into memory in 9 half-hour-safe API batches.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--batch-count", type=int, default=DEFAULT_BATCH_COUNT)
    parser.add_argument("--batch-index", default="auto", help="0-based batch index, or auto for next incomplete batch.")
    parser.add_argument("--key-cooldown-sec", type=int, default=1800)
    parser.add_argument("--wait-for-key", action="store_true", help="Wait until selected key is available. Default exits early if too soon.")
    parser.add_argument("--run-all", action="store_true", help="Run remaining batches in one process; use with --wait-for-key to sleep between key cooldowns.")
    parser.add_argument("--run-waves", action="store_true", help="Run 3 batches concurrently, wait between waves, and finish 9 batches in about 90 minutes.")
    parser.add_argument("--wave-sleep-sec", type=int, default=1800, help="Sleep between --run-waves waves; default 1800 sec = 30 minutes.")
    parser.add_argument("--dry-run", action="store_true", help="Build batches and print plan without calling the API or writing memories.")
    parser.add_argument("--no-repeat-fill", action="store_true", help="Require enough unique records; do not repeat-fill missing target counts.")
    parser.add_argument("--unique-only", action="store_true", help="Use only unique available mutation records instead of repeat-filling to target counts.")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "replay_state.json"
    records, parent_lookup, available_counts = build_replay_records(allow_repeat_fill=not args.no_repeat_fill, unique_only=args.unique_only)
    batches = chunk_records(records, args.batch_count)
    state = load_state(state_path, len(batches))
    completed = set(int(item) for item in state.get("completed_batches", []))
    config = load_project_config().llm
    keys = resolve_keys(config, max_keys=3)

    plan = {
        "target_counts": TARGET_COUNTS,
        "available_unique_counts": available_counts,
        "unique_only": args.unique_only,
        "replay_counts": dict(Counter(str(item.get("mutation_type")) for item in records)),
        "total_records": len(records),
        "batch_count": len(batches),
        "batch_sizes": [len(batch) for batch in batches],
        "key_count": len(keys),
        "schedule_note": "Use --run-waves to call 3 keys at once per wave; 9 batches finish in about 90 minutes with default 30-minute wave sleep.",
    }
    write_json(output_dir / "replay_plan.json", plan)
    if args.dry_run:
        print(json.dumps({"status": "dry_run", **plan}, ensure_ascii=False, indent=2, default=str))
        return 0

    def next_batch_index() -> int | None:
        if args.batch_index != "auto":
            return int(args.batch_index)
        for index in range(len(batches)):
            if index not in completed:
                return index
        return None

    reports: list[dict[str, Any]] = []
    if args.run_waves:
        while True:
            completed = set(int(item) for item in state.get("completed_batches", []))
            remaining = [index for index in range(len(batches)) if index not in completed]
            if not remaining:
                break
            wave_indices = remaining[: len(keys)]
            reports.extend(
                run_wave(
                    wave_indices=wave_indices,
                    batches=batches,
                    parent_lookup=parent_lookup,
                    config=config,
                    keys=keys,
                    output_dir=output_dir,
                    state=state,
                    state_path=state_path,
                    key_cooldown_sec=args.key_cooldown_sec,
                )
            )
            completed = set(int(item) for item in state.get("completed_batches", []))
            if len(completed) >= len(batches):
                break
            print(json.dumps({"event": "wave_sleep", "sleep_sec": args.wave_sleep_sec, "completed_batches": sorted(completed), "time": utc_now_iso()}, ensure_ascii=False), flush=True)
            time.sleep(max(0, args.wave_sleep_sec))
    else:
        while True:
            batch_index = next_batch_index()
            if batch_index is None:
                break
            key_index = batch_index % len(keys)
            if not wait_or_skip_key(state, key_index, wait_for_key=args.wait_for_key, state_path=state_path):
                print(json.dumps({"status": "key_cooling_down", "batch": batch_index + 1, "key_index": key_index + 1}, ensure_ascii=False, indent=2))
                return 0
            client = LLMClient(settings_for_key(config, keys[key_index]))
            try:
                report = run_one_batch(batch_index=batch_index, batches=batches, parent_lookup=parent_lookup, client=client, output_dir=output_dir)
            except Exception as exc:  # noqa: BLE001 - persist retry state for scheduled jobs.
                item = key_state(state, key_index)
                now = time.time()
                item["last_error"] = str(exc)[:500]
                item["last_used_ts"] = now
                item["next_available_ts"] = now + args.key_cooldown_sec
                item["error_count"] = int(item.get("error_count", 0)) + 1
                save_state(state_path, state)
                raise
            item = key_state(state, key_index)
            now = time.time()
            item["success_count"] = int(item.get("success_count", 0)) + 1
            item["last_used_ts"] = now
            item["next_available_ts"] = now + args.key_cooldown_sec
            completed.add(batch_index)
            state["completed_batches"] = sorted(completed)
            state["next_batch"] = min((index for index in range(len(batches)) if index not in completed), default=len(batches))
            save_state(state_path, state)
            reports.append(report)
            print(json.dumps({"event": "batch_done", "batch": batch_index + 1, "key_index": key_index + 1, "input_records": len(batches[batch_index])}, ensure_ascii=False), flush=True)
            if not args.run_all:
                break

    if len(completed) >= len(batches):
        before = memory_counts(output_dir)
        consolidation = consolidate_mutation_memory_dir(
            output_dir / "mutation_memory",
            policy=MemoryConsolidationPolicy(min_records=8, soft_chars=24000, hard_chars=28000, max_records_per_store=300),
            force=True,
        )
        after = memory_counts(output_dir)
        final_report = {
            "status": "complete",
            "plan": plan,
            "state": state,
            "before_consolidation_counts": before,
            "consolidation": consolidation,
            "after_consolidation_counts": after,
        }
        write_json(output_dir / "full_memory_replay_final_report.json", final_report)
        print(json.dumps(final_report, ensure_ascii=False, indent=2, default=str))
        return 0

    print(json.dumps({"status": "partial", "completed_batches": sorted(completed), "next_batch": state.get("next_batch"), "reports_written": [report["batch"] for report in reports]}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
