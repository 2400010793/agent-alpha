#!/usr/bin/env python3
"""Bounded integration test for all paper-discovery providers.

Writes one JSON object per step to a JSONL log. It is intentionally limited to
one known OpenAlex/arXiv seed and does not modify generated graphs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_graph.digest_adapter import load_digest_papers
from paper_graph.embeddings import LocalSemanticIndex, Specter2Encoder
from paper_graph.open_academic import OpenAcademicClient
from paper_graph.semantic_scholar import SemanticScholarClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", default="arxiv:1608.01795")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/generated/integration-tests/full-discovery")
    parser.add_argument("--openalex-cache", type=Path,
                        default=ROOT / "docs/generated/external-pilot/limit_order_book/openalex_cache.json")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    log_path = args.output / "graph_test_log.jsonl"
    log_path.write_text("", encoding="utf-8")
    events: list[dict[str, Any]] = []

    def record(step: str, status: str, **payload: Any) -> None:
        event = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "step": step, "status": status, **payload}
        events.append(event)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def run(step: str, fn: Callable[[], Any]) -> Any:
        started = time.monotonic()
        try:
            value = fn()
            size = len(value) if hasattr(value, "__len__") else None
            record(step, "ok", elapsed_seconds=round(time.monotonic() - started, 3), result_size=size)
            return value
        except Exception as error:
            record(step, "error", elapsed_seconds=round(time.monotonic() - started, 3),
                   error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
            return None

    openalex = OpenAcademicClient(timeout=20)
    scholar = SemanticScholarClient(timeout=20)
    def cached_openalex_seed() -> dict[str, Any] | None:
        try:
            return openalex.openalex_work(args.seed)
        except Exception as error:
            cache = json.loads(args.openalex_cache.read_text(encoding="utf-8")) if args.openalex_cache.exists() else {}
            manifest_path = ROOT / "docs/generated/parsed-paper-manifest/papers.jsonl"
            manifest_rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line]
            manifest_row = next((item for item in manifest_rows if item.get("paper_id") == args.seed), {})
            openalex_id = str((manifest_row.get("openalex") or {}).get("openalex_id") or "")
            row = cache.get(args.seed) or cache.get(f"openalex:{openalex_id}")
            if row:
                record("openalex_work_cache_fallback", "ok", reason=type(error).__name__, cache_key=args.seed)
                return row
            raise

    seed = run("openalex_work", cached_openalex_seed)
    if not seed:
        record("pipeline", "aborted", reason="OpenAlex seed lookup failed")
        return 1

    run("semantic_scholar_paper", lambda: scholar.paper(args.seed))
    run("semantic_scholar_citations", lambda: scholar._list_relation(args.seed, "citations", args.limit))
    run("semantic_scholar_references", lambda: scholar._list_relation(args.seed, "references", args.limit))
    run("semantic_scholar_recommendations", lambda: scholar.recommendations([args.seed], args.limit))
    run("crossref_search", lambda: openalex.crossref_search(seed.get("title", ""), args.limit))
    run("openalex_bibliographic_coupling", lambda: openalex.openalex_bibliographic_candidates(seed["id"], args.limit))

    local_papers = load_digest_papers(Path("/home/gaozh/my-paper-digest-new2"))
    local_seed = next((paper for paper in local_papers if str(paper.get("id")) == args.seed), None)
    if local_seed is None:
        local_seed = {"id": args.seed, "title": seed.get("title", ""), "abstract": seed.get("abstract", ""),
                      "authors": seed.get("authors", []), "year": seed.get("year")}
    try:
        encoder = Specter2Encoder()
        index = LocalSemanticIndex(local_papers or [local_seed], encoder=encoder, threshold=0.0)
        local_results = run("local_specter2", lambda: index.search(local_seed, limit=args.limit))
        if local_results is not None:
            record("local_specter2_summary", "ok", model=encoder.model_name,
                   returned=len(local_results), ids=[str(item.get("id")) for item in local_results])
    except Exception as error:
        record("local_specter2", "error", error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())

    ok_steps = [event["step"] for event in events if event["status"] == "ok"]
    failed_steps = [event["step"] for event in events if event["status"] == "error"]
    summary = {"seed": args.seed, "ok_steps": ok_steps, "failed_steps": failed_steps,
               "all_requested_provider_steps_ok": all(step in ok_steps for step in (
                   "semantic_scholar_citations", "semantic_scholar_recommendations", "local_specter2",
                   "crossref_search", "openalex_bibliographic_coupling"))}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if not failed_steps else 2


if __name__ == "__main__":
    raise SystemExit(main())
