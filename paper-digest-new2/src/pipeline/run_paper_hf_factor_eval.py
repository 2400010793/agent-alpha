#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run(command: list[str], *, timeout_sec: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_sec if timeout_sec > 0 else None,
        check=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and evaluate deterministic proxy factors from existing paper_hf_factors.")
    parser.add_argument("--input", default="data/analysis_archive.jsonl", help="JSONL input containing cumulative paper_hf_factors.")
    parser.add_argument("--factor-dir", default="data/paper_hf_factor_tests_v2", help="Directory for generated factor file.")
    parser.add_argument("--result-dir", default="data/paper_hf_factor_results_v2", help="Directory for fac-eval result JSON.")
    parser.add_argument("--dedup-key", default="paper_hf_direct_proxy_tests_v2", help="Generated factor stem/run id.")
    parser.add_argument("--config", default="", help="fac-eval YAML config. Defaults to fac-eval-demo/configs/small_eval.yaml via run_factor_eval.py.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum proxy variants; 0 means all renderable variants.")
    parser.add_argument("--python", default=str(PROJECT_ROOT / ".venv" / "bin" / "python"), help="Python executable for project and fac-eval.")
    parser.add_argument("--timeout-sec", type=int, default=1800, help="fac-eval timeout per factor file.")
    parser.add_argument("--skip-generate", action="store_true", help="Evaluate existing factor files without regenerating them.")
    parser.add_argument("--skip-eval", action="store_true", help="Only generate and compile factor files.")
    args = parser.parse_args()

    factor_dir = Path(args.factor_dir)
    if not factor_dir.is_absolute():
        factor_dir = PROJECT_ROOT / factor_dir
    result_dir = Path(args.result_dir)
    if not result_dir.is_absolute():
        result_dir = PROJECT_ROOT / result_dir

    if not args.skip_generate:
        generate_cmd = [
            args.python,
            "-m",
            "src.factor.generation.generate_paper_hf_factor_tests",
            "--input",
            args.input,
            "--output-dir",
            str(factor_dir),
            "--dedup-key",
            args.dedup_key,
            "--limit",
            str(args.limit),
        ]
        generated = _run(generate_cmd)
        if generated.returncode != 0:
            print(generated.stdout, end="")
            print(generated.stderr, end="", file=sys.stderr)
            raise SystemExit(generated.returncode)

    compile_cmd = [args.python, "-m", "py_compile", *[str(path) for path in sorted(factor_dir.glob("*.py"))]]
    compiled = _run(compile_cmd)
    if compiled.returncode != 0:
        print(compiled.stdout, end="")
        print(compiled.stderr, end="", file=sys.stderr)
        raise SystemExit(compiled.returncode)

    eval_payload = None
    if not args.skip_eval:
        eval_cmd = [
            args.python,
            "-m",
            "src.factor.calculation.run_factor_eval",
            "--python",
            args.python,
            "--factor-dir",
            str(factor_dir),
            "--result-dir",
            str(result_dir),
            "--force",
            "--timeout-sec",
            str(args.timeout_sec),
        ]
        if args.config:
            eval_cmd.extend(["--config", args.config])
        evaluated = _run(eval_cmd, timeout_sec=max(args.timeout_sec + 60, 120))
        if evaluated.returncode != 0:
            print(evaluated.stdout, end="")
            print(evaluated.stderr, end="", file=sys.stderr)
            raise SystemExit(evaluated.returncode)
        try:
            eval_payload = json.loads(evaluated.stdout)
        except json.JSONDecodeError:
            eval_payload = {"raw_stdout": evaluated.stdout[-2000:]}

    manifest_path = factor_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    print(
        json.dumps(
            {
                "status": "ok",
                "input": args.input,
                "factor_dir": str(factor_dir),
                "result_dir": str(result_dir),
                "dedup_key": args.dedup_key,
                "skip_generate": args.skip_generate,
                "variant_count": len(manifest.get("specs", [])),
                "eval": eval_payload,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()