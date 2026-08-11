#!/usr/bin/env python3
"""Expand matched arXiv papers through OpenAlex and retain arXiv-linked works.

The seed file is the completed arXiv→OpenAlex identity mapping. Expansion is
resumable and bounded: for each seed it samples explicit references and citing
works, fetches their full OpenAlex records, and keeps only works that expose an
arXiv identity. OpenAlex IDs are already authoritative for expanded works; no
fuzzy title matching is used in this stage.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from paper_graph.open_academic import OpenAcademicClient  # noqa: E402

ARXIV_RE = re.compile(r"(?:arxiv[:/]|arxiv\.org/(?:abs|pdf)/|10\.48550/arxiv\.)([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?", re.I)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def arxiv_from_work(work: dict[str, Any]) -> str | None:
    metadata = work.get("metadata") or {}
    for value in (metadata.get("arxiv_id"), metadata.get("arxiv_url"), metadata.get("doi"), work.get("url")):
        match = ARXIV_RE.search(str(value or ""))
        if match:
            return match.group(1)
    return None


def compact(work: dict[str, Any], seed_id: str, relation: str) -> dict[str, Any]:
    metadata = work.get("metadata") or {}
    openalex_id = str(work.get("id") or "").removeprefix("openalex:")
    return {
        "openalex_id": openalex_id,
        "openalex_url": f"https://openalex.org/{openalex_id}",
        "arxiv_id": arxiv_from_work(work),
        "identity_status": "arxiv_linked" if arxiv_from_work(work) else "openalex_only",
        "title": work.get("title") or "",
        "year": work.get("year"),
        "authors": work.get("authors") or [],
        "citation_count": work.get("citation_count", 0),
        "doi": metadata.get("doi"),
        "seed_openalex_id": seed_id,
        "relation": relation,
        "references": metadata.get("references") or [],
        "metadata": metadata,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=Path, default=ROOT / "docs/generated/arxiv-factor-8732-openalex-matches.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/generated/arxiv-factor-8732-openalex-expanded.jsonl")
    parser.add_argument("--cache", type=Path, default=ROOT / "docs/generated/arxiv-factor-8732-openalex-expanded-cache.jsonl")
    parser.add_argument("--max-seeds", type=int, default=0, help="0 means all matched seeds")
    parser.add_argument("--per-direction", type=int, default=10)
    parser.add_argument("--delay", type=float, default=30.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    seeds = []
    for row in read_jsonl(args.seeds):
        match = row.get("openalex") or {}
        if match.get("status") not in {"matched", "arxiv_linked"} or not match.get("openalex_id"):
            continue
        seeds.append({"arxiv_id": row.get("arxiv_id"), "title": row.get("title"), "openalex_id": str(match["openalex_id"])})
    seeds = seeds[:args.max_seeds] if args.max_seeds else seeds
    known_seed_ids = {seed["openalex_id"] for seed in seeds}
    cache = {str(row["openalex_id"]): row for row in read_jsonl(args.cache) if row.get("openalex_id")}
    candidates = {str(row["openalex_id"]): row for row in read_jsonl(args.output) if row.get("openalex_id")}
    client = OpenAcademicClient(timeout=args.timeout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    processed = set()

    def get_work(openalex_id: str) -> dict[str, Any]:
        key = openalex_id.removeprefix("openalex:")
        if key in cache:
            return cache[key]
        if args.delay:
            time.sleep(args.delay)
        work = client.openalex_work(f"openalex:{key}")
        cache[key] = work
        return work

    for index, seed in enumerate(seeds, 1):
        seed_id = seed["openalex_id"].removeprefix("openalex:")
        if seed_id in processed:
            continue
        try:
            seed_work = get_work(seed_id)
            references = list((seed_work.get("metadata") or {}).get("references") or [])[:args.per_direction]
            citing = client.openalex_citing_works(seed_id, args.per_direction)
            for relation, works in (("references", references), ("cited_by", citing)):
                for value in works:
                    candidate_id = str(value.get("id") if isinstance(value, dict) else value).rsplit("/", 1)[-1]
                    try:
                        work = value if isinstance(value, dict) and work_has_arxiv(value) else get_work(candidate_id)
                        row = compact(work, seed_id, relation)
                        if row["openalex_id"] not in known_seed_ids:
                            candidates[row["openalex_id"]] = row
                    except Exception as error:
                        continue
            processed.add(seed_id)
            print(json.dumps({"seed": index, "total": len(seeds), "seed_openalex_id": seed_id, "expanded_arxiv_candidates": len(candidates)}, ensure_ascii=False), flush=True)
        except Exception as error:
            print(json.dumps({"seed": index, "total": len(seeds), "seed_openalex_id": seed_id, "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False), flush=True)
        args.cache.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in cache.values()), encoding="utf-8")
        args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in candidates.values()), encoding="utf-8")

    print(json.dumps({"seeds": len(seeds), "processed": len(processed), "expanded_arxiv_candidates": len(candidates), "output": str(args.output), "cache": str(args.cache)}, ensure_ascii=False, indent=2))
    return 0


def work_has_arxiv(work: dict[str, Any]) -> bool:
    return bool(arxiv_from_work(work))


if __name__ == "__main__":
    raise SystemExit(main())
