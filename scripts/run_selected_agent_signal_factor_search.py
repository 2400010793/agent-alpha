from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from agent_alpha.config import load_project_config
from agent_alpha.factors.llm_factor_generator import generate_factor_candidates_with_llm
from agent_alpha.llm.client import LLMClient, LLMSettings, settings_from_env
from agent_alpha.search.factor_mutation import mcp_tools_for_mutation_focus
from agent_alpha.signals.signal_schema import validate_alpha_signal
from agent_alpha.workflows.batch_factor_iteration import run_batch_factor_iteration


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SIGNALS = PROJECT_ROOT / "outputs" / "hf_article_signal_scan_round2" / "selected_agent_signals.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "selected_agent_signal_factor_search"
FAC_EVAL_TEMPLATE = Path("/home/gaozh/fac-eval-demo/configs/small_eval.yaml")


def utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def parse_inline_keys(config: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for entry in config.get("api_key_envs", []):
        text = str(entry)
        if "=" in text:
            _, value = text.split("=", 1)
            if value.strip():
                keys.append(value.strip())
    if not keys:
        settings = settings_from_env(config)
        keys.append(settings.api_key)
    return keys[:3]


def is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return "429" in text or "too many" in text or "rate limit" in text or "ratelimit" in text


def is_timeout_error(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return "timeout" in text or "timed out" in text or "read timed out" in text or "connect timeout" in text


class RotatingLLMClient:
    def __init__(self, settings_by_key: list[LLMSettings], *, state_path: Path, cooldown_sec: int, rate_limit_backoff_sec: int, timeout_backoff_sec: int) -> None:
        self.clients = [LLMClient(settings) for settings in settings_by_key]
        self.state_path = state_path
        self.cooldown_sec = cooldown_sec
        self.rate_limit_backoff_sec = rate_limit_backoff_sec
        self.timeout_backoff_sec = timeout_backoff_sec
        self.state = self._load_state()
        self.settings = settings_by_key[0]

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            payload = load_json(self.state_path)
            if isinstance(payload, dict):
                return payload
        return {"created_at": utc_now_iso(), "keys": [{"key_index": index, "next_available_ts": 0.0, "success_count": 0, "rate_limit_count": 0, "timeout_count": 0, "error_count": 0} for index in range(len(self.clients))]}

    def _save_state(self) -> None:
        self.state["updated_at"] = utc_now_iso()
        write_json(self.state_path, self.state)

    def _key_state(self, index: int) -> dict[str, Any]:
        keys = self.state.setdefault("keys", [])
        while len(keys) <= index:
            keys.append({"key_index": len(keys), "next_available_ts": 0.0, "success_count": 0, "rate_limit_count": 0, "timeout_count": 0, "error_count": 0})
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

    def _record_success(self, index: int) -> None:
        state = self._key_state(index)
        now = time.time()
        state["success_count"] = int(state.get("success_count", 0)) + 1
        state["last_used_ts"] = now
        state["next_available_ts"] = now + self.cooldown_sec
        self._save_state()

    def _record_error(self, index: int, exc: BaseException, *, event_prefix: str) -> None:
        state = self._key_state(index)
        now = time.time()
        state["last_error"] = str(exc)[:500]
        state["last_error_at"] = utc_now_iso()
        if is_rate_limit_error(exc):
            state["rate_limit_count"] = int(state.get("rate_limit_count", 0)) + 1
            state["next_available_ts"] = now + self.rate_limit_backoff_sec
            event = f"{event_prefix}_rate_limited"
            sleep_sec = self.rate_limit_backoff_sec
        elif is_timeout_error(exc):
            state["timeout_count"] = int(state.get("timeout_count", 0)) + 1
            state["next_available_ts"] = now + self.timeout_backoff_sec
            event = f"{event_prefix}_timeout_backoff"
            sleep_sec = self.timeout_backoff_sec
        else:
            state["error_count"] = int(state.get("error_count", 0)) + 1
            state["next_available_ts"] = now + min(self.cooldown_sec, 300)
            event = f"{event_prefix}_error"
            sleep_sec = min(self.cooldown_sec, 300)
        print(json.dumps({"event": event, "key_index": index + 1, "sleep_key_sec": sleep_sec, "error": str(exc)[:240], "time": utc_now_iso()}, ensure_ascii=False), flush=True)
        self._save_state()

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        while True:
            index = self._select_key()
            try:
                print(json.dumps({"event": "llm_call_start", "key_index": index + 1, "time": utc_now_iso()}, ensure_ascii=False), flush=True)
                payload = self.clients[index].complete_json(messages)
                self._record_success(index)
                return payload
            except Exception as exc:  # noqa: BLE001
                self._record_error(index, exc, event_prefix="llm")

    def complete_json_with_mcp_tools(self, messages: list[dict[str, Any]], *, tool_names: list[str], role: str, max_tool_rounds: int = 4) -> dict[str, Any]:
        while True:
            index = self._select_key()
            try:
                print(json.dumps({"event": "llm_mcp_call_start", "key_index": index + 1, "tool_names": tool_names, "time": utc_now_iso()}, ensure_ascii=False), flush=True)
                payload = self.clients[index].complete_json_with_mcp_tools(messages, tool_names=tool_names, role=role, max_tool_rounds=max_tool_rounds)
                self._record_success(index)
                return payload
            except Exception as exc:  # noqa: BLE001
                self._record_error(index, exc, event_prefix="llm_mcp")


def build_rotating_client(output_dir: Path, *, cooldown_sec: int, rate_limit_backoff_sec: int, timeout_backoff_sec: int) -> RotatingLLMClient:
    config = load_project_config().llm
    keys = parse_inline_keys(config)
    if len(keys) < 3:
        raise RuntimeError(f"expected 3 API keys, got {len(keys)}")
    settings_by_key: list[LLMSettings] = []
    for key in keys[:3]:
        settings = settings_from_env(config, api_key=key)
        settings_by_key.append(LLMSettings(base_url=settings.base_url, api_key=settings.api_key, model=settings.model, timeout_sec=settings.timeout_sec, retries=1, min_interval_sec=0))
    return RotatingLLMClient(settings_by_key, state_path=output_dir / "llm_key_state.json", cooldown_sec=cooldown_sec, rate_limit_backoff_sec=rate_limit_backoff_sec, timeout_backoff_sec=timeout_backoff_sec)


def signal_list_from_payload(payload: Any) -> list[dict[str, Any]]:
    signals = payload.get("signals", []) if isinstance(payload, dict) else payload
    if not isinstance(signals, list):
        raise ValueError("signal payload must be a list or object with signals")
    out: list[dict[str, Any]] = []
    for signal in signals:
        if isinstance(signal, dict):
            payload_signal = dict(signal)
            payload_signal.setdefault("schema_version", "alpha_signal_v1")
            payload_signal.setdefault("created_at", utc_now_iso())
            validate_alpha_signal(payload_signal)
            out.append(payload_signal)
    return out


def write_signals_subset(signals: list[dict[str, Any]], output_dir: Path, *, limit: int | None = None) -> Path:
    selected = signals[:limit] if limit else signals
    path = output_dir / "input" / "signals.json"
    write_json(path, {"signals": selected, "created_at": utc_now_iso()})
    return path


def mcp_readiness_summary() -> dict[str, Any]:
    signal_to_factor_tools = [
        "market_data.list_fields",
        "market_data.recommend_fields",
        "evaluation_memory.get_good_bad_memory",
        "function_memory.search",
        "factor_registry.search_similar_factors",
        "factor.validate_candidate",
        "factor.render_and_compile_candidate",
    ]
    mutation_tools = {focus: mcp_tools_for_mutation_focus(focus) for focus in [
        "event_definition_mutation",
        "state_condition_mutation",
        "response_shape_mutation",
        "normalization_robustness_mutation",
        "time_structure_mutation",
        "refinement_simplification",
    ]}
    return {"signal_to_factor_tools": signal_to_factor_tools, "mutation_tools_by_focus": mutation_tools}


def dry_run(args: argparse.Namespace) -> dict[str, Any]:
    signals = signal_list_from_payload(load_json(args.signals))
    selected = signals[: args.limit_signals] if args.limit_signals else signals
    output_dir = Path(args.output_dir)
    signal_path = write_signals_subset(selected, output_dir, limit=None)
    return {
        "status": "dry_run",
        "signals_path": str(signal_path),
        "signal_count": len(selected),
        "target_agents": sorted({str(signal.get("target_agent") or "") for signal in selected if signal.get("target_agent")}),
        "factor_generations": args.factor_generations,
        "max_candidates_per_signal": args.max_candidates_per_signal,
        "max_new_candidates": args.max_new_candidates,
        "key_cooldown_sec": args.key_cooldown_sec,
        "rate_limit_backoff_sec": args.rate_limit_backoff_sec,
        "timeout_backoff_sec": args.timeout_backoff_sec,
        "run_fac_eval": bool(args.run_fac_eval),
        "summarize_generation_memory": bool(args.summarize_generation_memory),
        "mcp": mcp_readiness_summary(),
        "prompt_budget_controls": {
            "factor_generation_uses_mcp_tools": True,
            "factor_generation_retrieves_recommended_fields": True,
            "factor_generation_retrieves_similar_alpha_memory": True,
            "factor_mutation_uses_focus_specific_mcp_tools": True,
            "factor_mutation_compacts_memory_context": True,
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    signals = signal_list_from_payload(load_json(args.signals))
    signal_path = write_signals_subset(signals, output_dir, limit=args.limit_signals or None)
    client = build_rotating_client(
        output_dir,
        cooldown_sec=args.key_cooldown_sec,
        rate_limit_backoff_sec=args.rate_limit_backoff_sec,
        timeout_backoff_sec=args.timeout_backoff_sec,
    )
    return run_batch_factor_iteration(
        signal_path,
        output_dir=output_dir,
        client=client,
        generations=args.factor_generations,
        max_candidates_per_signal=args.max_candidates_per_signal,
        max_signal_mutations_per_signal=0,
        max_new_candidates=args.max_new_candidates,
        metrics_path=None,
        fac_eval_config_path=args.fac_eval_config_template,
        run_fac_eval=args.run_fac_eval,
        exploration_direction=args.exploration_direction,
        seed_factor_candidates=[],
        summarize_generation_memory=args.summarize_generation_memory,
        memory_consolidation_records=args.memory_consolidation_records,
        memory_consolidation_soft_chars=args.memory_consolidation_soft_chars,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run selected article-derived agent signals through factor generation, evaluation, memory update, and mutation search.")
    parser.add_argument("--signals", default=str(DEFAULT_SIGNALS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--limit-signals", type=int, default=0, help="Optional first-N signal limit for smoke runs.")
    parser.add_argument("--factor-generations", type=int, default=22)
    parser.add_argument("--max-candidates-per-signal", type=int, default=1)
    parser.add_argument("--max-new-candidates", type=int, default=1)
    parser.add_argument("--fac-eval-config-template", default=str(FAC_EVAL_TEMPLATE))
    parser.add_argument("--run-fac-eval", action="store_true")
    parser.add_argument("--summarize-generation-memory", action="store_true")
    parser.add_argument("--memory-consolidation-records", type=int, default=8)
    parser.add_argument("--memory-consolidation-soft-chars", type=int, default=24000)
    parser.add_argument("--key-cooldown-sec", type=int, default=1800)
    parser.add_argument("--rate-limit-backoff-sec", type=int, default=7200)
    parser.add_argument("--timeout-backoff-sec", type=int, default=7200)
    parser.add_argument("--exploration-direction", default="selected article-derived specialist agent signals; robust non-duplicate factor search with MCP validation and memory updates")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    summary = dry_run(args) if args.dry_run else run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if summary.get("status") in {"ok", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
