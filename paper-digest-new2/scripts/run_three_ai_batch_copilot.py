#!/usr/bin/env python3
"""Run trusted papers through reading and generic Graph research analysis."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm.three_ai.opinion_analysis import generate_article_opinions  # noqa: E402
from src.llm.three_ai.pipeline import (  # noqa: E402
    RESEARCH_TOPIC_LABELS,
    build_evidence_pack_v2,
    build_reading_note_single_call_chunked,
    infer_research_topic_category,
    read_jsonl_valid,
)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def trusted_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
        checks = pack.get("quality_checks") if isinstance(pack.get("quality_checks"), dict) else {}
        if pack.get("status") != "ok" or checks.get("is_trusted") is not True:
            continue
        article_id = str(row.get("arxiv_id") or pack.get("arxiv_id") or row.get("source_id") or "").strip()
        if article_id:
            latest[article_id] = row
    return list(latest.values())


def append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()


def run_one(row: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    article_id = str(row.get("arxiv_id") or row.get("source_id") or "unknown")
    pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
    common = {
        "model": args.model,
        "copilot_bin": args.copilot_bin,
        "timeout_sec": args.timeout_sec,
    }
    os.environ["PAPER_AIC_ONLY"] = "0"
    os.environ.pop("PAPER_LLM_DIRECT_API", None)
    os.environ["PAPER_LLM_ARTICLE_ID"] = article_id

    os.environ["PAPER_LLM_STAGE"] = "reading"
    os.environ["PAPER_LLM_KEY_ALIAS"] = "key2"
    note = build_reading_note_single_call_chunked(row, pack, api_key_env=args.reading_key_env, **common)

    os.environ["PAPER_LLM_STAGE"] = "opinion"
    os.environ["PAPER_LLM_KEY_ALIAS"] = "key1"
    evidence_v2 = build_evidence_pack_v2(pack)
    opinions = generate_article_opinions(
        row, note, evidence_v2, copilot_json=_copilot_json,
        model=args.model, copilot_bin=args.copilot_bin,
        timeout_sec=args.timeout_sec, api_key_env=args.opinion_key_env,
    )

    research_topic = infer_research_topic_category(row, note)
    research_topic_label = RESEARCH_TOPIC_LABELS[research_topic]
    note["research_topic_category"] = research_topic
    note["research_topic_label"] = research_topic_label
    return {
        **row,
        "llm_reading_note": note,
        "article_opinions": opinions,
        "research_contributions": list(opinions.get("research_contributions") or []),
        "relation_candidates": list(opinions.get("relation_candidates") or []),
        "research_ideas": list(opinions.get("research_ideas") or []),
        "analysis_validation": dict(opinions.get("analysis_validation") or {}),
        "llm_audit_status": "not_run_not_required",
        "llm_input_evidence_pack_v2": evidence_v2,
        "reading_recommendation_score": note.get("recommendation_score"),
        "research_topic_category": research_topic,
        "research_topic_label": research_topic_label,
        "analysis_pipeline": "paper-reading-generic-research-v2-copilot-p",
        "analysis_agent": args.model,
        "analysis_pending_llm": False,
        "copilot_bin": args.copilot_bin,
        "fetched_at": now(),
    }


def _copilot_json(**kwargs: Any) -> Dict[str, Any]:
    # Imported lazily so this script cannot accidentally use the direct API branch.
    from src.llm.three_ai.pipeline import copilot_json
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            return copilot_json(**kwargs)
        except Exception as exc:
            last_error = exc
            if attempt == 3:
                raise
            print(json.dumps({"status": "stage_retry", "stage": os.environ.get("PAPER_LLM_STAGE"), "article_id": os.environ.get("PAPER_LLM_ARTICLE_ID"), "attempt": attempt, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), flush=True)
            time.sleep(1)
    raise last_error or RuntimeError("copilot stage failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-archive", type=Path, default=ROOT / "data/arxiv_evidence_archive.jsonl")
    parser.add_argument("--output-archive", type=Path, default=ROOT / "data/opinion_batch_analysis_gpt54mini_20260724.jsonl")
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--copilot-bin", default="/home/gaozh/.local/bin/copilot-p")
    parser.add_argument("--timeout-sec", type=int, default=900)
    parser.add_argument("--reading-key-env", default="")
    parser.add_argument("--opinion-key-env", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-truncate", action="store_true", help="append to an existing output archive instead of replacing it")
    args = parser.parse_args()
    evidence_archive = args.evidence_archive if args.evidence_archive.is_absolute() else ROOT / args.evidence_archive
    output_archive = args.output_archive if args.output_archive.is_absolute() else ROOT / args.output_archive
    if not args.no_truncate:
        output_archive.parent.mkdir(parents=True, exist_ok=True)
        output_archive.write_text("", encoding="utf-8")
    rows = trusted_rows(read_jsonl_valid(evidence_archive))
    if args.limit > 0:
        rows = rows[: args.limit]
    succeeded = failed = 0
    for index, row in enumerate(rows, 1):
        article_id = str(row.get("arxiv_id") or row.get("source_id") or "unknown")
        print(json.dumps({"status": "starting", "index": index, "total": len(rows), "arxiv_id": article_id, "model": args.model}, ensure_ascii=False), flush=True)
        try:
            result = run_one(row, args)
            append_jsonl(output_archive, result)
            succeeded += 1
            print(json.dumps({"status": "ok", "arxiv_id": article_id}, ensure_ascii=False), flush=True)
        except Exception as exc:  # one bad article must not stop the batch
            failed += 1
            append_jsonl(output_archive, {"status": "failed", "arxiv_id": article_id, "title": row.get("title"), "model": args.model, "error": f"{type(exc).__name__}: {exc}", "failed_at": now()})
            print(json.dumps({"status": "failed", "arxiv_id": article_id, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), flush=True)
    print(json.dumps({"status": "batch_complete", "trusted_count": len(rows), "succeeded": succeeded, "failed": failed, "output_archive": str(output_archive)}, ensure_ascii=False), flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
