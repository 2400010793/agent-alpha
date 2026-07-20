from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent_alpha.config import load_project_config, project_path
from agent_alpha.factors.expression_validator import validate_factor_candidate
from agent_alpha.factors.fac_eval_adapter import py_compile_factor_file, write_fac_eval_config
from agent_alpha.factors.factor_file_renderer import render_factor_file
from agent_alpha.factors.llm_factor_generator import generate_factor_candidates_with_llm
from agent_alpha.llm.client import LLMClient, settings_from_env
from agent_alpha.signals.reading_gate import ReadingGateConfig, evaluate_reading_gate
from agent_alpha.signals.llm_signal_generator import generate_signals_from_reading_note
from agent_alpha.workflows.ingest_local_paper import ingest_local_document


class FakeLLMClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "signals": [
                    {
                        "signal_id": "sig_lob_imbalance",
                        "source_paper_id": "paper_demo",
                        "source_reading_note_id": "paper_demo",
                        "signal_name": "LOB imbalance pressure",
                        "market_intuition": "Visible bid depth exceeding ask depth may proxy buying pressure.",
                        "hypothesis": "Top-book imbalance can forecast short-horizon continuation.",
                        "expected_direction": "positive",
                        "hf_mechanism_tags": ["order_book_pressure"],
                        "candidate_fields": ["bidV1", "askV1"],
                        "evidence_ids": ["ev_0001"],
                    }
                ]
            }
        return {
            "factor_candidates": [
                {
                    "factor_id": "lob_imbalance_l1",
                    "name": "lob_imbalance_l1",
                    "prefix_expression": ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]],
                    "expression": "safe_div(bidV1 - askV1, bidV1 + askV1)",
                    "fields": ["bidV1", "askV1"],
                    "windows": [],
                    "direction": "positive",
                    "source_signal_id": "sig_lob_imbalance",
                    "source_reading_note_id": "paper_demo",
                    "mechanism_tags": ["order_book_pressure"],
                }
            ]
        }


def _write_json(path: str | Path, payload: Any) -> str:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(output_path)


def _load_reading_note(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _resolve_ingest_path(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute() or candidate.exists():
        return str(candidate)
    return str(project_path(path))


def build_client(*, fake_llm: bool, api_key: str | None, model: str | None) -> LLMClient | FakeLLMClient:
    if fake_llm:
        return FakeLLMClient()
    config = load_project_config().llm
    settings = settings_from_env(config, api_key=api_key, model=model)
    return LLMClient(settings)


def run_workflow(
    *,
    paper: str | Path,
    output_dir: str | Path,
    factor_dir: str | Path,
    fac_eval_config: str | Path,
    api_key: str | None = None,
    model: str | None = None,
    client: LLMClient | FakeLLMClient | None = None,
    fake_llm: bool = False,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    summary: dict[str, Any] = {
        "status": "failed",
        "paper_id": "",
        "reading_note": "",
        "reading_gate": {},
        "signals_path": "",
        "factor_candidates_path": "",
        "rendered_factor_files": [],
        "fac_eval_config": "",
        "errors": errors,
    }

    ingest_result = ingest_local_document(paper)
    paper_id = str(ingest_result["paper_id"])
    reading_note_path = project_path(str(ingest_result["reading_note"]))
    reading_note = _load_reading_note(reading_note_path)
    gate_config = ReadingGateConfig.from_mapping(load_project_config().signal_generation.get("reading_gate", {}))
    gate = evaluate_reading_gate(reading_note, gate_config)
    summary.update({"paper_id": paper_id, "reading_note": str(reading_note_path), "reading_gate": gate.to_dict()})

    if not gate.should_continue:
        summary["status"] = "gated"
        _write_json(output_path / "summary.json", summary)
        return summary

    llm_client = client or build_client(fake_llm=fake_llm, api_key=api_key, model=model)
    signals = generate_signals_from_reading_note(reading_note, llm_client)
    signals_path = _write_json(output_path / "signals.json", {"signals": signals})
    summary["signals_path"] = signals_path
    if not signals:
        summary["status"] = "no_signal"
        _write_json(output_path / "summary.json", summary)
        return summary

    all_candidates: list[dict[str, Any]] = []
    rendered_factor_files: list[str] = []
    for signal in signals:
        candidates = generate_factor_candidates_with_llm(signal, llm_client)
        for candidate in candidates:
            validation = validate_factor_candidate(candidate)
            candidate["validation_status"] = "passed" if validation.ok else "failed"
            candidate["validation_message"] = validation.message
            if not validation.ok:
                errors.append(f"{candidate.get('factor_id', 'unknown')}: {validation.message}")
                all_candidates.append(candidate)
                continue
            rendered = render_factor_file(candidate, factor_dir)
            compile_result = py_compile_factor_file(rendered)
            candidate["factor_file"] = str(rendered)
            candidate["py_compile"] = {
                "ok": compile_result.returncode == 0,
                "returncode": compile_result.returncode,
                "stderr": compile_result.stderr,
            }
            if compile_result.returncode == 0:
                rendered_factor_files.append(str(rendered))
            else:
                errors.append(f"{candidate.get('factor_id', 'unknown')}: py_compile failed: {compile_result.stderr}")
            all_candidates.append(candidate)

    candidates_path = _write_json(output_path / "factor_candidates.json", {"factor_candidates": all_candidates})
    summary["factor_candidates_path"] = candidates_path
    summary["rendered_factor_files"] = rendered_factor_files
    if rendered_factor_files:
        summary["fac_eval_config"] = str(write_fac_eval_config(rendered_factor_files, fac_eval_config))
        summary["status"] = "ok"
    else:
        summary["status"] = "failed"
    _write_json(output_path / "summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local paper/text -> reading note -> gated AlphaSignal -> FactorCandidate -> fac-eval config.")
    parser.add_argument("--paper", required=True, help="Local paper, Markdown, or text path.")
    parser.add_argument("--api-key", default=None, help="LLM API key. If omitted, environment variables from configs/llm.yaml are used.")
    parser.add_argument("--model", default=None, help="LLM model override, e.g. openai/gpt-4o.")
    parser.add_argument("--output-dir", required=True, help="Directory for summary, signals, and candidate JSON.")
    parser.add_argument("--factor-dir", required=True, help="Directory for rendered fac-eval-compatible factor files.")
    parser.add_argument("--fac-eval-config", required=True, help="Output fac-eval-demo config path.")
    parser.add_argument("--fake-llm", action="store_true", help="Use fixed local fake LLM responses; no API key is read.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_workflow(
        paper=_resolve_ingest_path(args.paper),
        output_dir=args.output_dir,
        factor_dir=args.factor_dir,
        fac_eval_config=args.fac_eval_config,
        api_key=args.api_key,
        model=args.model,
        fake_llm=args.fake_llm,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] in {"ok", "gated", "no_signal"} else 1


if __name__ == "__main__":
    raise SystemExit(main())