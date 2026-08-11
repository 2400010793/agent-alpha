from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_alpha.evaluation.research_evaluator import evaluate_research_quality
from agent_alpha.evaluation.review_report_writer import write_review_report


def _load_json(path: str | Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON input must be an object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate high-frequency factor research quality.")
    parser.add_argument("--factor", required=True, help="Factor candidate JSON object.")
    parser.add_argument("--metrics", default="", help="Optional metrics JSON object.")
    parser.add_argument("--output", default="", help="Optional review report path (.json or .md).")
    args = parser.parse_args(argv)
    candidate = _load_json(args.factor)
    metrics = _load_json(args.metrics) if args.metrics else {}
    review = evaluate_research_quality(candidate, metrics, compile_result={"ok": True})
    if args.output:
        write_review_report(args.output, review)
    print(json.dumps(review, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())