#!/usr/bin/env python3
"""Evaluate independently populated Gate 2 human labels without rewriting them."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from paper_graph.gate2_audit import evaluate_review_labels, read_candidate_rows


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-sample", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--accepted-precision-threshold", type=float, default=0.90)
    args = parser.parse_args()
    rows = read_candidate_rows([args.review_sample])
    result = evaluate_review_labels(
        rows, accepted_precision_threshold=args.accepted_precision_threshold
    )
    _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["finance_review_status"] != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())