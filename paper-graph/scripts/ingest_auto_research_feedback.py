#!/usr/bin/env python3
"""Validate Agent Alpha opportunity feedback and emit bounded graph updates."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from paper_graph.opportunity_feedback import (
    OpportunityResearchFeedbackV1,
    derive_graph_feedback_update,
)


def atomic_write(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feedback", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.replace:
        raise SystemExit(f"output exists; use --replace: {args.output}")
    feedback = OpportunityResearchFeedbackV1.from_mapping(
        json.loads(args.feedback.read_text(encoding="utf-8"))
    )
    update = derive_graph_feedback_update(feedback)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(args.output, update.to_dict())
    print(json.dumps({
        "output": str(args.output),
        "feedback_update_id": update.feedback_update_id,
        "action_codes": list(update.action_codes),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
