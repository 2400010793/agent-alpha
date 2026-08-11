#!/usr/bin/env python3
"""Paper Digest CLI: reading -> generic graph research analysis -> validation."""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.llm.three_ai.pipeline import (
    build_reading_note,
    build_reading_note_chunked,
    build_reading_note_single_call_chunked,
    copilot_json,
    read_jsonl_valid,
    select_trusted_evidence,
    upsert_row,
)
from src.llm.three_ai.opinion_analysis import generate_article_opinions
from src.arxiv.evidence_v2 import build_evidence_pack_v2


def run_article(row: Dict[str, Any], pack: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    os.environ["PAPER_AIC_ONLY"] = "1" if args.aic_only else "0"
    os.environ["PAPER_LLM_ARTICLE_ID"] = str(row.get("arxiv_id") or row.get("source_id") or row.get("title") or "unknown")
    if args.aic_only:
        test_dir = Path(args.aic_test_dir)
        if not test_dir.is_absolute():
            test_dir = Path(args.project_root).resolve() / test_dir
        os.environ["PAPER_AIC_PROMPT_DIR"] = str(test_dir)
    os.environ["PAPER_LLM_STAGE"] = "reading"
    os.environ["PAPER_LLM_KEY_ALIAS"] = "key2"
    reading_cache = None
    opinion_cache = None
    if args.reading_note_cache_dir and not args.aic_only:
        cache_dir = Path(args.reading_note_cache_dir)
        if not cache_dir.is_absolute():
            cache_dir = Path(args.project_root).resolve() / cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        article_id = str(row.get("arxiv_id") or row.get("source_id") or "article").replace("/", "_")
        reading_cache = cache_dir / f"{article_id}.json"
    if args.opinion_cache_dir and not args.aic_only:
        cache_dir = Path(args.opinion_cache_dir)
        if not cache_dir.is_absolute():
            cache_dir = Path(args.project_root).resolve() / cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        article_id = str(row.get("arxiv_id") or row.get("source_id") or "article").replace("/", "_")
        opinion_cache = cache_dir / f"{article_id}.json"
    if args.only_opinion:
        source = Path(args.reading_note_source)
        if not source.is_absolute():
            source = Path(args.project_root).resolve() / source
        cached = json.loads(source.read_text(encoding="utf-8"))
        note = cached.get("llm_reading_note") if isinstance(cached, dict) else None
        if not isinstance(note, dict):
            raise RuntimeError(f"--only-opinion requires llm_reading_note in {source}")
    elif reading_cache and reading_cache.exists() and not args.aic_only:
        cached = json.loads(reading_cache.read_text(encoding="utf-8"))
        note = cached.get("llm_reading_note") if isinstance(cached, dict) else None
        if not isinstance(note, dict):
            raise RuntimeError(f"reading cache does not contain llm_reading_note: {reading_cache}")
        print(json.dumps({"status": "reading_cache_reused", "article_id": row.get("arxiv_id"), "path": str(reading_cache)}, ensure_ascii=False))
    elif args.single_call_chunked_reading:
        note = build_reading_note_single_call_chunked(row, pack, model=args.reading_model, copilot_bin=args.copilot_bin, timeout_sec=args.timeout_sec, api_key_env=args.reading_key_env)
    elif args.chunked_reading:
        note = build_reading_note_chunked(row, pack, model=args.reading_model, copilot_bin=args.copilot_bin, timeout_sec=args.timeout_sec, api_key_env=args.reading_key_env, chunk_cache_dir=Path(args.reading_chunk_cache_dir) if args.reading_chunk_cache_dir else None)
    else:
        note = build_reading_note(row, pack, model=args.reading_model, copilot_bin=args.copilot_bin, timeout_sec=args.timeout_sec, api_key_env=args.reading_key_env)

    if reading_cache and not reading_cache.exists() and not args.aic_only:
        reading_cache.write_text(json.dumps({"arxiv_id": row.get("arxiv_id"), "llm_reading_note": note}, ensure_ascii=False, indent=2), encoding="utf-8")

    reading_score = float(note.get("recommendation_score") or 0)
    if not args.aic_only and not args.only_opinion and not args.disable_reading_gate and reading_score < args.reading_gate_score:
        return {
            **row,
            "llm_reading_note": note,
            "reading_recommendation_score": reading_score,
            "analysis_status": "filtered",
            "analysis_pipeline": "paper-reading-generic-research-v2",
            "analysis_pending_llm": False,
            "reading_gate": {
                "passed": False,
                "threshold": args.reading_gate_score,
                "score": reading_score,
                "reason": "reading recommendation score below gate threshold",
            },
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    if args.call_interval_sec > 0 and not args.only_opinion:
        time.sleep(args.call_interval_sec)

    evidence_v2 = build_evidence_pack_v2(pack)
    if opinion_cache and opinion_cache.exists() and not args.only_opinion:
        cached = json.loads(opinion_cache.read_text(encoding="utf-8"))
        opinions = cached.get("article_opinions") if isinstance(cached, dict) else None
        if not isinstance(opinions, dict):
            raise RuntimeError(f"opinion cache does not contain article_opinions: {opinion_cache}")
        print(json.dumps({"status": "opinion_cache_reused", "article_id": row.get("arxiv_id"), "path": str(opinion_cache)}, ensure_ascii=False))
    else:
        os.environ["PAPER_LLM_STAGE"] = "opinion"
        os.environ["PAPER_LLM_KEY_ALIAS"] = "key1"
        opinions = generate_article_opinions(row, note, evidence_v2, copilot_json=copilot_json, model=args.opinion_model, copilot_bin=args.copilot_bin, timeout_sec=args.timeout_sec, api_key_env=args.opinion_key_env)
        if opinion_cache and not args.aic_only:
            opinion_cache.write_text(json.dumps({"arxiv_id": row.get("arxiv_id"), "article_opinions": opinions}, ensure_ascii=False, indent=2), encoding="utf-8")
    result = dict(row)
    result.update({
        "llm_reading_note": note,
        "article_opinions": opinions,
        "research_contributions": list(opinions.get("research_contributions") or []),
        "relation_candidates": list(opinions.get("relation_candidates") or []),
        "research_ideas": list(opinions.get("research_ideas") or []),
        "analysis_validation": dict(opinions.get("analysis_validation") or {}),
        "llm_audit_status": "not_run_not_required",
        "llm_input_evidence_pack_v2": evidence_v2,
        "reading_recommendation_score": note.get("recommendation_score"),
        "analysis_status": "ok",
        "reading_gate": {
            "passed": True,
            "threshold": args.reading_gate_score,
            "score": reading_score,
        },
        "analysis_pipeline": "paper-reading-generic-research-v2",
        "analysis_agent": opinions.get("analysis_agent"),
        "analysis_pending_llm": False,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Paper Digest: evidence-grounded generic Graph/Auto-Research analysis.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--evidence-archive", default="data/arxiv_evidence_archive.jsonl")
    parser.add_argument("--output", default="data/latest_opinion_digest.json")
    parser.add_argument("--analysis-archive", default="data/opinion_analysis_archive.jsonl")
    parser.add_argument("--arxiv-id", default="")
    parser.add_argument("--title-contains", default="")
    parser.add_argument("--reading-model", default=os.environ.get("PAPER_READING_LLM_MODEL", "gpt-4.1"))
    parser.add_argument("--opinion-model", default=os.environ.get("PAPER_OPINION_LLM_MODEL", "gpt-4.1"))
    parser.add_argument("--reading-key-env", default=os.environ.get("PAPER_READING_LLM_KEY_ENV", ""))
    parser.add_argument("--opinion-key-env", default=os.environ.get("PAPER_OPINION_LLM_KEY_ENV", ""))
    parser.add_argument("--copilot-bin", default=os.environ.get("PAPER_COPILOT_BIN", "copilot"))
    parser.add_argument("--timeout-sec", type=int, default=int(os.environ.get("PAPER_THREE_AI_TIMEOUT_SEC", "300")))
    parser.add_argument("--chunked-reading", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--single-call-chunked-reading", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--only-opinion", action="store_true", help="reuse a cached reading note and run only the opinion/idea line")
    parser.add_argument("--reading-note-source", default="data/latest_three_ai_result.json", help="JSON result containing llm_reading_note for --only-opinion")
    parser.add_argument("--call-interval-sec", type=float, default=0.0, help="sleep between completed LLM calls")
    parser.add_argument("--reading-gate-score", type=float, default=4.0, help="minimum Reading recommendation score required before Opinion/Audit")
    parser.add_argument("--disable-reading-gate", action="store_true", help="run Opinion/Audit even when Reading score is below the gate")
    parser.add_argument("--article-interval-sec", type=float, default=0.0, help="sleep between completed articles")
    parser.add_argument("--reading-note-cache-dir", default="", help="cache completed Reading notes for reuse after interruption; disabled by --aic-only")
    parser.add_argument("--reading-chunk-cache-dir", default="", help="cache individual Reading chunks for reuse after interruption; disabled by --aic-only")
    parser.add_argument("--opinion-cache-dir", default="", help="cache completed Opinion results for reuse after interruption; disabled by --aic-only")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--aic-only", action="store_true", help="send all stage prompts to the CLI, show terminal usage, ignore model JSON, and write no result files")
    parser.add_argument("--aic-test-dir", default="aic_tests/1912.09363", help="directory for the three exact AIC-only stage prompts")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    rows = read_jsonl_valid(root / args.evidence_archive)
    row, pack = select_trusted_evidence(rows, arxiv_id=args.arxiv_id, title_contains=args.title_contains)
    if args.dry_run:
        print(json.dumps({"status": "dry_run", "title": row.get("title"), "url": row.get("url"), "pipeline": "paper-reading-generic-research-v2"}, ensure_ascii=False))
        return 0
    result = run_article(row, pack, args)
    if args.aic_only:
        print(json.dumps({"status": "aic_only_complete", "article_id": args.arxiv_id}, ensure_ascii=False))
        return 0
    upsert_row(root / args.analysis_archive, result)
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result.get("analysis_status", "ok"), "title": result.get("title"), "pipeline": result.get("analysis_pipeline"), "contribution_count": len(result.get("research_contributions") or []), "idea_count": len(result.get("research_ideas") or []), "validation_status": (result.get("analysis_validation") or {}).get("status"), "reading_gate": result.get("reading_gate")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
