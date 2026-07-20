from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_alpha.config import load_project_config
from agent_alpha.roles import THREE_ROLES
from agent_alpha.signals.reading_gate import ReadingGateConfig, evaluate_reading_gate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate high-frequency alpha signals from prebuilt reading notes. Paper crawling is intentionally out of scope."
    )
    parser.add_argument("--reading-note", help="Path to a reading_note_v1 JSON file produced by another pipeline.")
    parser.add_argument("--output", default="outputs/signal_runs/signals.json", help="Output JSON path.")
    parser.add_argument("--min-reading-score", type=float, default=None, help="Override reading gate minimum score.")
    parser.add_argument("--dry-run", action="store_true", help="Only print role and config summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_project_config()
    if args.dry_run or not args.reading_note:
        print(json.dumps({
            "status": "ok",
            "mode": "dry_run",
            "roles": [role.__dict__ for role in THREE_ROLES],
            "allowed_field_count": len(config.field_registry.get("allowed_input_fields", [])),
            "note": "paper crawling is skipped; pass --reading-note from an external crawler/reader",
        }, ensure_ascii=False, indent=2))
        return 0

    note_path = Path(args.reading_note).expanduser().resolve()
    reading_note = json.loads(note_path.read_text(encoding="utf-8"))
    signal_cfg = config.signal_generation.get("reading_gate", {}) if hasattr(config, "signal_generation") else {}
    gate_config = ReadingGateConfig.from_mapping(signal_cfg)
    if args.min_reading_score is not None:
        gate_config = ReadingGateConfig(
            min_recommendation_score=args.min_reading_score,
            require_evidence=gate_config.require_evidence,
            require_trading_intuition=gate_config.require_trading_intuition,
            min_mechanism_chain_items=gate_config.min_mechanism_chain_items,
            gated_pipeline_name=gate_config.gated_pipeline_name,
            gated_reason_prefix=gate_config.gated_reason_prefix,
        )
    gate = evaluate_reading_gate(reading_note, gate_config)
    if not gate.should_continue:
        payload = {
            "status": "gated",
            "analysis_pipeline": gate.pipeline_name,
            "reading_note_path": str(note_path),
            "reading_note_schema": reading_note.get("schema_version"),
            "reading_gate": gate.to_dict(),
            "signals": [],
            "next_step": "Stop before Idea Person LLM; reading note is unlikely to contain usable high-frequency signals.",
        }
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    payload = {
        "status": "planned",
        "reading_note_path": str(note_path),
        "reading_note_schema": reading_note.get("schema_version"),
        "reading_gate": gate.to_dict(),
        "next_step": "Use Idea Person LLM skill to emit AlphaSignal objects.",
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())