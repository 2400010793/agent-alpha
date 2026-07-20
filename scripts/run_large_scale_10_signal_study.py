from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agent_alpha.config import load_project_config
from agent_alpha.evaluation.fac_eval_result_reader import read_stock_level_metrics
from agent_alpha.llm.client import LLMClient, LLMSettings, settings_from_env
from agent_alpha.signals.signal_schema import validate_alpha_signal
from agent_alpha.workflows.batch_factor_iteration import run_batch_factor_iteration


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "large_scale_10_signal_study"
REAL_PAPER_SIGNALS = PROJECT_ROOT / "outputs" / "real_e2e" / "hft_synchronizes_prices_1211_1919" / "llm_signals_rerun.json"
ELITE_SIGNALS = Path("/home/gaozh/fac-idea-study/elite_deduped_safe_signals.json")
FAC_EVAL_TEMPLATE = Path("/home/gaozh/fac-eval-demo/configs/small_eval.yaml")
DEFAULT_VARIANT_CANDIDATES = (
    PROJECT_ROOT / "outputs" / "manual_mutation_backtest" / "manual_mutation_candidates.json",
    PROJECT_ROOT / "outputs" / "manual_mutation_round2" / "manual_mutation_round2_candidates.json",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def append_jsonl(path: str | Path, payload: dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def signal_list_from_payload(payload: Any) -> list[dict[str, Any]]:
    signals = payload.get("signals", []) if isinstance(payload, dict) else payload
    if not isinstance(signals, list):
        raise ValueError("signal payload must be a list or object with signals")
    return [dict(signal) for signal in signals if isinstance(signal, dict)]


def candidate_list_from_payload(payload: Any) -> list[dict[str, Any]]:
    candidates = payload.get("factor_candidates", payload.get("candidates", [])) if isinstance(payload, dict) else payload
    if not isinstance(candidates, list):
        raise ValueError("candidate payload must be a list or object with factor_candidates")
    return [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]


def safe_signal(signal: dict[str, Any]) -> dict[str, Any]:
    payload = dict(signal)
    payload.setdefault("schema_version", "alpha_signal_v1")
    payload.setdefault("created_at", utc_now_iso())
    validate_alpha_signal(payload)
    return payload


def build_ten_signal_file(output_dir: Path, *, force: bool = False) -> Path:
    out = output_dir / "input" / "ten_signals.json"
    if out.exists() and not force:
        return out
    real_signals = [safe_signal(signal) for signal in signal_list_from_payload(load_json(REAL_PAPER_SIGNALS))]
    elite_signals = [safe_signal(signal) for signal in signal_list_from_payload(load_json(ELITE_SIGNALS))]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for signal in [*real_signals[:3], *elite_signals]:
        signal_id = str(signal.get("signal_id") or "")
        if not signal_id or signal_id in seen:
            continue
        seen.add(signal_id)
        selected.append(signal)
        if len(selected) >= 10:
            break
    if len(selected) != 10:
        raise RuntimeError(f"expected 10 signals, got {len(selected)}")
    write_json(out, {"signals": selected})
    return out


def load_variant_candidates(paths: list[str | Path]) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        for candidate in candidate_list_from_payload(load_json(path)):
            factor_id = str(candidate.get("factor_id") or candidate.get("name") or "")
            if not factor_id or factor_id in seen:
                continue
            seen.add(factor_id)
            candidate.setdefault("created_by", "large_scale_seed_variant")
            variants.append(candidate)
    return variants


def _overlap_score(signal: dict[str, Any], candidate: dict[str, Any]) -> tuple[int, int, int, str]:
    signal_tags = set(str(tag) for tag in signal.get("hf_mechanism_tags", []) if str(tag))
    candidate_tags = set(str(tag) for tag in candidate.get("mechanism_tags", []) if str(tag))
    signal_fields = set(str(field) for field in signal.get("candidate_fields", []) if str(field))
    candidate_fields = set(str(field) for field in candidate.get("fields", []) if str(field))
    signal_id = str(signal.get("signal_id") or "")
    source_signal_id = str(candidate.get("source_signal_id") or "")
    explicit = int(signal_id and signal_id in source_signal_id)
    return (explicit, len(signal_tags & candidate_tags), len(signal_fields & candidate_fields), str(candidate.get("factor_id") or candidate.get("name") or ""))


def select_seed_variants_for_signal(signal: dict[str, Any], variants: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    selected = [dict(candidate) for score, candidate in sorted(((_overlap_score(signal, candidate), candidate) for candidate in variants), key=lambda item: item[0], reverse=True) if score[:3] != (0, 0, 0)]
    if len(selected) < limit and any(str(tag) in {"order_book_pressure", "spread_liquidity", "trade_impact"} for tag in signal.get("hf_mechanism_tags", [])):
        for candidate in variants:
            if "depth_imbalance" in str(candidate.get("factor_id", "")) and all(candidate.get("factor_id") != item.get("factor_id") for item in selected):
                selected.append(dict(candidate))
    return selected[:limit]


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


class RotatingLLMClient:
    def __init__(
        self,
        settings_by_key: list[LLMSettings],
        *,
        state_path: Path,
        cooldown_sec: int,
        rate_limit_backoff_sec: int,
    ) -> None:
        self.clients = [LLMClient(settings) for settings in settings_by_key]
        self.state_path = state_path
        self.cooldown_sec = cooldown_sec
        self.rate_limit_backoff_sec = rate_limit_backoff_sec
        self.state = self._load_state()
        self.settings = settings_by_key[0]

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
        last_error: BaseException | None = None
        while True:
            index = self._select_key()
            state = self._key_state(index)
            try:
                print(json.dumps({"event": "llm_call_start", "key_index": index + 1, "time": utc_now_iso()}, ensure_ascii=False), flush=True)
                payload = self.clients[index].complete_json(messages)
                now = time.time()
                state["success_count"] = int(state.get("success_count", 0)) + 1
                state["last_used_ts"] = now
                state["next_available_ts"] = now + self.cooldown_sec
                self._save_state()
                return payload
            except Exception as exc:  # noqa: BLE001 - this is a long-running resiliency boundary.
                now = time.time()
                last_error = exc
                state["last_error"] = str(exc)[:500]
                state["last_error_at"] = utc_now_iso()
                if is_rate_limit_error(exc):
                    state["rate_limit_count"] = int(state.get("rate_limit_count", 0)) + 1
                    state["next_available_ts"] = now + self.rate_limit_backoff_sec
                    print(json.dumps({"event": "llm_rate_limited", "key_index": index + 1, "sleep_key_sec": self.rate_limit_backoff_sec, "time": utc_now_iso()}, ensure_ascii=False), flush=True)
                else:
                    state["error_count"] = int(state.get("error_count", 0)) + 1
                    state["next_available_ts"] = now + min(self.cooldown_sec, 300)
                    print(json.dumps({"event": "llm_error", "key_index": index + 1, "error": str(exc)[:240], "time": utc_now_iso()}, ensure_ascii=False), flush=True)
                self._save_state()
                if not any(float(self._key_state(i).get("next_available_ts", 0.0)) <= time.time() for i in range(len(self.clients))):
                    continue
            if last_error and not is_rate_limit_error(last_error):
                continue

    def complete_json_with_mcp_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tool_names: list[str],
        role: str,
        max_tool_rounds: int = 4,
    ) -> dict[str, Any]:
        last_error: BaseException | None = None
        while True:
            index = self._select_key()
            state = self._key_state(index)
            try:
                print(json.dumps({"event": "llm_mcp_call_start", "key_index": index + 1, "tool_names": tool_names, "time": utc_now_iso()}, ensure_ascii=False), flush=True)
                payload = self.clients[index].complete_json_with_mcp_tools(messages, tool_names=tool_names, role=role, max_tool_rounds=max_tool_rounds)
                now = time.time()
                state["success_count"] = int(state.get("success_count", 0)) + 1
                state["last_used_ts"] = now
                state["next_available_ts"] = now + self.cooldown_sec
                self._save_state()
                return payload
            except Exception as exc:  # noqa: BLE001 - this is a long-running resiliency boundary.
                now = time.time()
                last_error = exc
                state["last_error"] = str(exc)[:500]
                state["last_error_at"] = utc_now_iso()
                if is_rate_limit_error(exc):
                    state["rate_limit_count"] = int(state.get("rate_limit_count", 0)) + 1
                    state["next_available_ts"] = now + self.rate_limit_backoff_sec
                    print(json.dumps({"event": "llm_mcp_rate_limited", "key_index": index + 1, "sleep_key_sec": self.rate_limit_backoff_sec, "time": utc_now_iso()}, ensure_ascii=False), flush=True)
                else:
                    state["error_count"] = int(state.get("error_count", 0)) + 1
                    state["next_available_ts"] = now + min(self.cooldown_sec, 300)
                    print(json.dumps({"event": "llm_mcp_error", "key_index": index + 1, "error": str(exc)[:240], "time": utc_now_iso()}, ensure_ascii=False), flush=True)
                self._save_state()
                if not any(float(self._key_state(i).get("next_available_ts", 0.0)) <= time.time() for i in range(len(self.clients))):
                    continue
            if last_error and not is_rate_limit_error(last_error):
                continue


def build_rotating_client(output_dir: Path, *, cooldown_sec: int, rate_limit_backoff_sec: int) -> RotatingLLMClient:
    config = load_project_config().llm
    keys = parse_inline_keys(config)
    if len(keys) < 3:
        raise RuntimeError(f"expected 3 API keys, got {len(keys)}")
    settings_by_key: list[LLMSettings] = []
    for key in keys[:3]:
        settings = settings_from_env(config, api_key=key)
        settings_by_key.append(LLMSettings(
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            timeout_sec=settings.timeout_sec,
            retries=1,
            min_interval_sec=0,
        ))
    return RotatingLLMClient(
        settings_by_key,
        state_path=output_dir / "llm_key_state.json",
        cooldown_sec=cooldown_sec,
        rate_limit_backoff_sec=rate_limit_backoff_sec,
    )


def generation_summaries(run_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted((run_dir / "iteration").glob("generation_*/summary.json")):
        payload = load_json(path)
        if isinstance(payload, dict):
            payload["summary_path"] = str(path)
            out.append(payload)
    return out


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def metrics_by_factor_from_generation_summaries(summaries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        metrics_path = summary.get("fac_eval_metrics_path")
        if not metrics_path:
            continue
        path = Path(str(metrics_path))
        if not path.exists():
            continue
        for row in read_stock_level_metrics(path):
            factor_id = str(row.get("factor_id") or row.get("factor_name") or row.get("name") or "")
            if factor_id:
                metrics[factor_id] = row
    return metrics


def summarize_run(signal: dict[str, Any], run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    generation_rows = generation_summaries(run_dir)
    metric_lookup = metrics_by_factor_from_generation_summaries(generation_rows)
    eval_records = load_jsonl(run_dir / "iteration" / "evaluation_records.jsonl")
    candidate_pool = load_jsonl(run_dir / "iteration" / "candidate_pool.jsonl")
    initial_candidates = load_json(run_dir / "initial" / "factor_candidates.json").get("factor_candidates", []) if (run_dir / "initial" / "factor_candidates.json").exists() else []
    computable: list[dict[str, Any]] = []
    for candidate in initial_candidates:
        factor_id = str(candidate.get("factor_id") or candidate.get("name") or "")
        if candidate.get("py_compile", {}).get("ok"):
            computable.append({
                "signal_id": signal.get("signal_id"),
                "factor_id": factor_id,
                "name": candidate.get("name"),
                "factor_file": candidate.get("factor_file"),
                "fields": candidate.get("fields"),
                "windows": candidate.get("windows"),
                "prefix_expression": candidate.get("prefix_expression"),
                "metrics": metric_lookup.get(factor_id, {}),
            })
    review_by_factor = {str(row.get("factor_id") or ""): row for row in eval_records}
    return {
        "signal_id": signal.get("signal_id"),
        "run_dir": str(run_dir),
        "status": summary.get("status"),
        "signal_mutation_count": summary.get("signal_mutation_count"),
        "factor_input_signal_count": summary.get("factor_input_signal_count"),
        "initial_candidate_count": summary.get("initial_candidate_count"),
        "generation_count": len(generation_rows),
        "rendered_factor_files": summary.get("iteration", {}).get("rendered_factor_files", []),
        "computable_factor_count": len(computable),
        "computable_factors": computable,
        "reviews": [
            {
                "factor_id": row.get("factor_id"),
                "decision": row.get("decision"),
                "failure_modes": row.get("failure_modes"),
                "metrics": row.get("metrics"),
                "statistical_summary": row.get("statistical_summary"),
            }
            for row in eval_records
        ],
        "candidate_pool_count": len(candidate_pool),
        "accepted_count": sum(1 for row in review_by_factor.values() if row.get("decision") == "accept"),
    }


def run_study(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    signals_path = build_ten_signal_file(output_dir, force=args.rebuild_signals)
    signals = signal_list_from_payload(load_json(signals_path))
    variants = load_variant_candidates(args.variant_candidates)
    write_json(output_dir / "input" / "seed_variant_candidates.json", {"factor_candidates": variants})
    client = build_rotating_client(output_dir, cooldown_sec=args.key_cooldown_sec, rate_limit_backoff_sec=args.rate_limit_backoff_sec)
    overall_path = output_dir / "overall_summary.json"
    completed: dict[str, Any] = {}
    if overall_path.exists() and not args.restart:
        previous = load_json(overall_path)
        if isinstance(previous, dict):
            completed = {str(row.get("signal_id")): row for row in previous.get("runs", []) if isinstance(row, dict)}

    runs: list[dict[str, Any]] = list(completed.values())
    for index, signal in enumerate(signals, start=1):
        signal_id = str(signal.get("signal_id"))
        if signal_id in completed and not args.restart:
            print(json.dumps({"event": "skip_completed_signal", "signal_id": signal_id, "index": index}, ensure_ascii=False), flush=True)
            continue
        run_dir = output_dir / "runs" / f"{index:02d}_{signal_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        per_signal_path = run_dir / "signal.json"
        write_json(per_signal_path, {"signals": [signal]})
        seed_variants = select_seed_variants_for_signal(signal, variants, limit=args.max_seed_variants_per_signal)
        write_json(run_dir / "seed_variants.json", {"factor_candidates": seed_variants})
        print(json.dumps({"event": "start_signal", "index": index, "signal_id": signal_id, "time": utc_now_iso()}, ensure_ascii=False), flush=True)
        try:
            summary = run_batch_factor_iteration(
                per_signal_path,
                output_dir=run_dir,
                client=client,
                generations=args.factor_generations,
                max_candidates_per_signal=args.max_candidates_per_signal,
                max_signal_mutations_per_signal=args.signal_mutations,
                max_new_candidates=args.max_new_candidates,
                metrics_path=None,
                fac_eval_config_path=args.fac_eval_config_template,
                run_fac_eval=True,
                exploration_direction=args.exploration_direction,
                seed_factor_candidates=seed_variants,
            )
            run_summary = summarize_run(signal, run_dir, summary)
            run_summary["finished_at"] = utc_now_iso()
            append_jsonl(output_dir / "computable_factors.jsonl", {"signal_id": signal_id, "computable_factors": run_summary["computable_factors"], "finished_at": run_summary["finished_at"]})
        except Exception as exc:  # noqa: BLE001 - keep long run resumable.
            run_summary = {"signal_id": signal_id, "run_dir": str(run_dir), "status": "failed", "error": str(exc), "finished_at": utc_now_iso()}
            append_jsonl(output_dir / "run_errors.jsonl", run_summary)
            print(json.dumps({"event": "signal_failed", "signal_id": signal_id, "error": str(exc)[:500]}, ensure_ascii=False), flush=True)
        completed[signal_id] = run_summary
        runs = list(completed.values())
        overall = {
            "status": "running" if len(completed) < len(signals) else "ok",
            "updated_at": utc_now_iso(),
            "signals_path": str(signals_path),
            "requested_signal_count": len(signals),
            "variant_candidate_count": len(variants),
            "max_seed_variants_per_signal": args.max_seed_variants_per_signal,
            "completed_signal_count": len(completed),
            "successful_signal_count": sum(1 for row in runs if row.get("status") == "ok"),
            "failed_signal_count": sum(1 for row in runs if row.get("status") == "failed"),
            "computable_factor_count": sum(int(row.get("computable_factor_count", 0)) for row in runs),
            "runs": runs,
        }
        write_json(overall_path, overall)
        print(json.dumps({"event": "finish_signal", "signal_id": signal_id, "status": run_summary.get("status"), "computable_factor_count": run_summary.get("computable_factor_count", 0)}, ensure_ascii=False), flush=True)
    final = load_json(overall_path) if overall_path.exists() else {"status": "no_runs"}
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the 10-signal large scale Agent Alpha study with key rotation and real fac-eval.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--fac-eval-config-template", default=str(FAC_EVAL_TEMPLATE))
    parser.add_argument("--signal-mutations", type=int, default=4)
    parser.add_argument("--factor-generations", type=int, default=7, help="7 generations means up to 6 factor-mutation transitions.")
    parser.add_argument("--max-candidates-per-signal", type=int, default=1)
    parser.add_argument("--max-new-candidates", type=int, default=1)
    parser.add_argument("--variant-candidates", action="append", default=[str(path) for path in DEFAULT_VARIANT_CANDIDATES], help="FactorCandidate JSON file with variants to seed into matching signal runs. Can be repeated.")
    parser.add_argument("--max-seed-variants-per-signal", type=int, default=3)
    parser.add_argument("--key-cooldown-sec", type=int, default=1800)
    parser.add_argument("--rate-limit-backoff-sec", type=int, default=10800)
    parser.add_argument("--exploration-direction", default="fac-idea verified mechanisms; robust non-cosmetic signal and factor mutation")
    parser.add_argument("--rebuild-signals", action="store_true")
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args(argv)
    summary = run_study(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if summary.get("status") in {"ok", "running"} else 1


if __name__ == "__main__":
    raise SystemExit(main())