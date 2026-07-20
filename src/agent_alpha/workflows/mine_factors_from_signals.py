from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_alpha.factors.expression_validator import validate_factor_candidate
from agent_alpha.factors.fac_eval_adapter import py_compile_factor_file, write_fac_eval_config
from agent_alpha.factors.factor_file_renderer import render_factor_file
from agent_alpha.factors.llm_factor_generator import generate_factor_candidates_with_llm
from agent_alpha.factors.template_factor_generator import generate_template_factor_candidates
from agent_alpha.llm.client import LLMClient, settings_from_env
from agent_alpha.config import load_project_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mine factor candidates from gated high-frequency signals.")
    parser.add_argument("--signals", required=True, help="Signal JSON produced by generate_signals_from_papers or a list of AlphaSignal objects.")
    parser.add_argument("--output", default="outputs/factor_runs/factor_candidates.json", help="Output candidate JSON path.")
    parser.add_argument("--factor-dir", default="data/factors/rendered", help="Directory for fac-eval-compatible factor files.")
    parser.add_argument("--fac-eval-config", default="outputs/factor_runs/fac_eval_config.yaml", help="Output fac-eval-demo compatible config path.")
    parser.add_argument("--baseline-template", action="store_true", help="Use temporary non-LLM template baseline instead of LLM Implementer.")
    parser.add_argument("--api-key", default=None, help="LLM API key. If omitted, environment variables from configs/llm.yaml are used.")
    parser.add_argument("--model", default=None, help="LLM model override.")
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.signals).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("status") == "gated":
        out = {"status": "gated", "reason": "input_signal_file_was_gated", "factor_candidates": []}
    else:
        signals = payload.get("signals") if isinstance(payload, dict) else payload
        if not isinstance(signals, list):
            raise ValueError("--signals must contain a list or an object with signals")
        candidates: list[dict] = []
        rendered_files: list[str] = []
        client = None
        if not args.baseline_template:
            settings = settings_from_env(load_project_config().llm, api_key=args.api_key, model=args.model)
            client = LLMClient(settings)
        for signal in signals:
            generated = generate_template_factor_candidates(signal) if args.baseline_template else generate_factor_candidates_with_llm(signal, client)
            for candidate in generated:
                validation = validate_factor_candidate(candidate)
                candidate["validation_status"] = "passed" if validation.ok else "failed"
                candidate["validation_message"] = validation.message
                if validation.ok:
                    factor_file = render_factor_file(candidate, args.factor_dir)
                    compile_result = py_compile_factor_file(factor_file)
                    candidate["factor_file"] = str(factor_file)
                    candidate["py_compile"] = {
                        "ok": compile_result.returncode == 0,
                        "returncode": compile_result.returncode,
                        "stderr": compile_result.stderr,
                    }
                    if compile_result.returncode == 0:
                        rendered_files.append(str(factor_file))
                candidates.append(candidate)
        fac_eval_config = str(write_fac_eval_config(rendered_files, args.fac_eval_config)) if rendered_files else ""
        out = {"status": "ok", "factor_candidates": candidates, "fac_eval_config": fac_eval_config}
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())