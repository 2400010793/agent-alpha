from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_alpha.config import load_project_config
from agent_alpha.llm.client import LLMClient, LLMSettings, settings_from_env
from agent_alpha.search.experiment_runner import run_search_experiment


"""
Run an existing-signal/existing-factor mutation-memory smoke for 6 iterations.

This script intentionally does not run paper reading. It starts from an existing
FactorCandidate JSON file and uses the mutation/evaluation loop to update:

- specialist_memory
- function_memory
- transfer_memory
- mutation_arm_memory

Half-hour scheduling note:
  To invoke one 6-iteration job every 30 minutes from cron, use:

    */30 * * * * cd /home/gaozh/agent_alpha && PYTHONPATH=src python scripts/run_existing_factor_memory_6iter.py --output-dir outputs/scheduled_memory_$(date +\%Y\%m\%d_\%H\%M)

  For one long-running process that waits for key cooldowns internally, keep the
  default --key-cooldown-sec 1800. With three keys, the first three LLM calls can
  use key 1/2/3, then the client waits until the earliest key is available.
"""


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED_CANDIDATES = PROJECT_ROOT / "outputs" / "real_llm_3gen_with_signal_mutation_smoke" / "initial" / "factor_candidates.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "existing_factor_memory_6iter"


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
        raise ValueError("candidate payload must be a list or an object with factor_candidates")
    return [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]


def parse_three_keys(config: dict[str, Any]) -> list[str]:
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
        if len(keys) >= 3:
            break
    if not keys:
        keys.append(settings_from_env(config).api_key)
    return keys[:3]


def is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return "429" in text or "too many" in text or "rate limit" in text or "ratelimit" in text


class RotatingLLMClient:
    def __init__(
        self,
        settings_by_key: list[LLMSettings],
        *,
        state_path: Path,
        key_cooldown_sec: int,
        rate_limit_backoff_sec: int,
    ) -> None:
        if not settings_by_key:
            raise ValueError("at least one LLM key is required")
        self.clients = [LLMClient(settings) for settings in settings_by_key]
        self.settings = settings_by_key[0]
        self.state_path = state_path
        self.key_cooldown_sec = key_cooldown_sec
        self.rate_limit_backoff_sec = rate_limit_backoff_sec
        self.state = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            payload = load_json(self.state_path)
            if isinstance(payload, dict):
                return payload
        return {
            "created_at": utc_now_iso(),
            "keys": [
                {"key_index": index, "next_available_ts": 0.0, "success_count": 0, "rate_limit_count": 0, "error_count": 0}
                for index in range(len(self.clients))
            ],
        }

    def _save_state(self) -> None:
        self.state["updated_at"] = utc_now_iso()
        write_json(self.state_path, self.state)

    def _key_state(self, index: int) -> dict[str, Any]:
        keys = self.state.setdefault("keys", [])
        while len(keys) <= index:
            keys.append({"key_index": len(keys), "next_available_ts": 0.0, "success_count": 0, "rate_limit_count": 0, "error_count": 0})
        return keys[index]

    def _select_key(self) -> int:
        while True:
            now = time.time()
            states = [self._key_state(index) for index in range(len(self.clients))]
            available = [state for state in states if float(state.get("next_available_ts", 0.0)) <= now]
            if available:
                selected = min(available, key=lambda item: (float(item.get("last_used_ts", 0.0)), int(item.get("key_index", 0))))
                return int(selected["key_index"])
            earliest = min(float(state.get("next_available_ts", 0.0)) for state in states)
            sleep_sec = max(1.0, earliest - now)
            print(json.dumps({"event": "all_keys_cooling_down", "sleep_sec": round(sleep_sec, 1), "time": utc_now_iso()}, ensure_ascii=False), flush=True)
            time.sleep(sleep_sec)

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return self._call("complete_json", messages)

    def complete_json_with_mcp_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tool_names: list[str],
        role: str,
        max_tool_rounds: int = 4,
    ) -> dict[str, Any]:
        return self._call(
            "complete_json_with_mcp_tools",
            messages,
            tool_names=tool_names,
            role=role,
            max_tool_rounds=max_tool_rounds,
        )

    def _call(self, method_name: str, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        last_error: BaseException | None = None
        for _ in range(max(1, len(self.clients) * 2)):
            index = self._select_key()
            state = self._key_state(index)
            try:
                print(json.dumps({"event": "llm_call_start", "key_index": index + 1, "method": method_name, "time": utc_now_iso()}, ensure_ascii=False), flush=True)
                payload = getattr(self.clients[index], method_name)(messages, **kwargs)
                now = time.time()
                state["success_count"] = int(state.get("success_count", 0)) + 1
                state["last_used_ts"] = now
                state["next_available_ts"] = now + self.key_cooldown_sec
                self._save_state()
                return payload
            except Exception as exc:  # noqa: BLE001 - long-running API rotation boundary.
                now = time.time()
                last_error = exc
                state["last_error"] = str(exc)[:500]
                state["last_used_ts"] = now
                if is_rate_limit_error(exc):
                    state["rate_limit_count"] = int(state.get("rate_limit_count", 0)) + 1
                    state["next_available_ts"] = now + self.rate_limit_backoff_sec
                else:
                    state["error_count"] = int(state.get("error_count", 0)) + 1
                    state["next_available_ts"] = now + min(120, self.key_cooldown_sec)
                self._save_state()
                print(json.dumps({"event": "llm_call_error", "key_index": index + 1, "error": str(exc)[:300], "time": utc_now_iso()}, ensure_ascii=False), flush=True)
        raise RuntimeError(f"all rotating LLM keys failed; last_error={last_error}")


def build_rotating_client(config: dict[str, Any], *, state_path: Path, key_cooldown_sec: int, rate_limit_backoff_sec: int) -> RotatingLLMClient:
    keys = parse_three_keys(config)
    settings = [settings_from_env(config, api_key=key) for key in keys]
    return RotatingLLMClient(settings, state_path=state_path, key_cooldown_sec=key_cooldown_sec, rate_limit_backoff_sec=rate_limit_backoff_sec)


def summarize_memory_files(output_dir: Path) -> dict[str, int]:
    memory_root = output_dir / "mutation_memory"
    if not memory_root.exists():
        return {}
    counts: dict[str, int] = {}
    for path in sorted(memory_root.rglob("*.jsonl")):
        counts[str(path.relative_to(output_dir))] = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run 6 mutation-memory iterations from existing factor candidates; no paper reading.")
    parser.add_argument("--seed-factor-candidates", default=str(DEFAULT_SEED_CANDIDATES), help="Existing FactorCandidate JSON file.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory for iteration artifacts and run-local memory.")
    parser.add_argument("--iterations", type=int, default=6, help="Mutation/evaluation generations to run.")
    parser.add_argument("--max-new-candidates", type=int, default=1, help="New LLM mutation candidates per generation.")
    parser.add_argument("--key-cooldown-sec", type=int, default=1800, help="Cooldown after a successful call per key; 1800 sec = half an hour.")
    parser.add_argument("--rate-limit-backoff-sec", type=int, default=1800, help="Cooldown after 429/rate-limit errors per key.")
    parser.add_argument("--memory-consolidation-records", type=int, default=8, help="Consolidate specialist/function/transfer memory when a store reaches this many records.")
    parser.add_argument("--memory-consolidation-soft-chars", type=int, default=24000, help="Consolidate specialist/function/transfer memory when a store reaches this many chars.")
    parser.add_argument("--summarize-generation-memory", action="store_true", help="Also call LLM memory summarization once per generation.")
    parser.add_argument("--exploration-direction", default="6-iteration memory update from existing factors; avoid reading; produce non-cosmetic specialist mutations.")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    client = build_rotating_client(
        load_project_config().llm,
        state_path=output_dir / "llm_key_state.json",
        key_cooldown_sec=args.key_cooldown_sec,
        rate_limit_backoff_sec=args.rate_limit_backoff_sec,
    )
    candidates = candidate_list_from_payload(load_json(args.seed_factor_candidates))[:1]
    if not candidates:
        raise ValueError("no seed factor candidates found")

    summary = run_search_experiment(
        candidates,
        output_dir=output_dir,
        generations=max(1, args.iterations),
        max_new_candidates=args.max_new_candidates,
        client=client,  # type: ignore[arg-type]
        exploration_direction=args.exploration_direction,
        summarize_generation_memory=args.summarize_generation_memory,
        memory_consolidation_records=args.memory_consolidation_records,
        memory_consolidation_soft_chars=args.memory_consolidation_soft_chars,
    )
    report = {
        "status": summary.get("status"),
        "iterations": args.iterations,
        "seed_factor_id": candidates[0].get("factor_id"),
        "output_dir": str(output_dir),
        "summary": summary,
        "memory_counts": summarize_memory_files(output_dir),
        "half_hour_note": "Default key cooldown is 1800 seconds. For cron every half hour: */30 * * * * cd /home/gaozh/agent_alpha && PYTHONPATH=src python scripts/run_existing_factor_memory_6iter.py --output-dir outputs/scheduled_memory_$(date +\\%Y\\%m\\%d_\\%H\\%M)",
    }
    write_json(output_dir / "six_iteration_memory_summary.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())