#!/usr/bin/env python3
"""Prepare a compact manifest from completed three-stage papers."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DIGEST_ROOT = ROOT.parent / "my-paper-digest-new2"
TAXONOMY_FILE = DIGEST_ROOT / "src" / "taxonomy" / "extract_topics.py"


def has(value: Any) -> bool:
    return value not in (None, "", [], {})


def pick(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    return next((row.get(key) for key in keys if has(row.get(key))), None)


def canonical_id(row: dict[str, Any]) -> str:
    value = re.sub(r"^arxiv:", "", str(row.get("arxiv_id") or row.get("id") or "").strip(), flags=re.I)
    return re.sub(r"v\d+$", "", value, flags=re.I)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def complete(row: dict[str, Any]) -> bool:
    return all(has(pick(row, keys)) for keys in (
        ("llm_reading_note", "reading_note", "reading_note_v1"),
        ("paper_hf_factors", "article_opinions", "opinion_analysis"),
        ("llm_faithfulness_audit", "faithfulness_audit", "llm_opinion_faithfulness_audit"),
    ))


def load_taxonomy() -> list[dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("paper_graph_taxonomy", TAXONOMY_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load taxonomy: {TAXONOMY_FILE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return [{"parent_id": parent["id"], "parent_label": parent["label"], "id": child_id,
             "label": values[0], "terms": tuple(str(term).casefold() for term in values[1:])}
            for parent in module.TAXONOMY for child_id, values in parent["children"].items()]


def paper_text(row: dict[str, Any]) -> tuple[str, str]:
    note = pick(row, ("llm_reading_note", "reading_note", "reading_note_v1")) or {}
    evidence = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
    values: list[Any] = [row.get("title")]
    if isinstance(note, dict):
        values.extend(note.get(key) for key in ("central_claim", "problem", "method_logic", "mechanism_chain", "core_formulas", "data_and_empirical_setup", "key_results"))
    values.extend(evidence.get(key) for key in ("intro_context", "section_overview", "method_evidence", "data_sample_evidence", "variable_definitions"))
    text = " ".join(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "") for value in values).casefold()
    return str(row.get("title") or "").strip(), text


def classify(row: dict[str, Any], taxonomy: list[dict[str, Any]], max_topics: int) -> list[dict[str, Any]]:
    title, text = paper_text(row)
    title_text = title.casefold()
    matches = []
    for topic in taxonomy:
        hits = [term for term in topic["terms"] if term in text]
        title_hits = [term for term in topic["terms"] if term in title_text]
        if hits:
            matches.append({"topic_id": topic["id"], "parent_id": topic["parent_id"], "label": topic["label"],
                            "score": len(set(hits)) + 2 * len(set(title_hits)),
                            "matched_terms": sorted(set(hits)), "title_terms": sorted(set(title_hits))})
    matches.sort(key=lambda item: (-item["score"], -len(item["title_terms"]), item["topic_id"]))
    return matches[:max_topics]


def _request_json(url: str, *, attempts: int = 5) -> dict[str, Any]:
    """GET JSON with bounded 429/network retries and explicit failure classes."""
    request = Request(url, headers={"User-Agent": "paper-graph/0.1 (mailto:paper-graph@example.org)"})
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as error:
            last_error = error
            if error.code not in {408, 429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise
            retry_after = error.headers.get("Retry-After")
            try:
                wait_seconds = max(5.0, float(retry_after)) if retry_after else 5.0 * (2 ** attempt)
            except ValueError:
                wait_seconds = 5.0 * (2 ** attempt)
            time.sleep(wait_seconds)
        except (TimeoutError, URLError) as error:
            last_error = error
            if attempt == attempts - 1:
                raise
            time.sleep(5.0 * (2 ** attempt))
    raise RuntimeError(f"OpenAlex request failed: {last_error}")


def _openalex_result(item: dict[str, Any], *, method: str, score: float | None = None) -> dict[str, Any]:
    doi = item.get("doi")
    return {"status": "matched", "match_method": method,
            "score": round(score, 4) if score is not None else 1.0,
            "openalex_id": str(item.get("id") or "").rsplit("/", 1)[-1],
            "title": item.get("title"), "doi": doi,
            "year": item.get("publication_year"), "cited_by_count": item.get("cited_by_count", 0),
            "reference_count": len(item.get("referenced_works") or []),
            "referenced_works": item.get("referenced_works") or []}


def openalex_match(row: dict[str, Any]) -> dict[str, Any]:
    """Resolve a local arXiv paper by exact ID only.

    An empty successful arXiv-ID query is treated as ``not_indexed``.  Title
    search is intentionally not used because it can map a paper to the wrong
    OpenAlex work.
    """
    arxiv_id = canonical_id(row)
    if not arxiv_id:
        return {"status": "missing_arxiv_id", "arxiv_id": ""}

    exact = _request_json(
        f"https://api.openalex.org/works?filter=ids.arxiv:{quote(arxiv_id)}&per-page=1"
    )
    exact_results = exact.get("results", [])
    if not exact_results:
        return {"status": "not_indexed", "match_method": "arxiv_id", "arxiv_id": arxiv_id}
    return _openalex_result(exact_results[0], method="arxiv_id", score=1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DIGEST_ROOT / "data" / "three_ai_deduplicated_archive.jsonl")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs" / "generated" / "parsed-paper-manifest")
    parser.add_argument("--max-topics", type=int, default=2)
    parser.add_argument("--openalex", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=float, default=3.0, help="seconds between OpenAlex requests")
    args = parser.parse_args()
    if args.max_topics < 1:
        raise SystemExit("--max-topics must be positive")
    rows = sorted((row for row in read_jsonl(args.input) if complete(row)), key=canonical_id)
    if args.limit > 0:
        rows = rows[:args.limit]
    taxonomy = load_taxonomy()
    records = []
    cache_path = args.output_dir / "openalex_cache.jsonl"
    cache = {canonical_id(row): row.get("openalex", {}) for row in read_jsonl(cache_path)} if cache_path.exists() else {}
    for row in rows:
        paper_id = canonical_id(row)
        title = str(row.get("title") or "").strip()
        record = {"paper_id": f"arxiv:{paper_id}", "arxiv_id": paper_id, "title": title,
                  "url": row.get("url") or f"https://arxiv.org/abs/{paper_id}",
                  "parsed_manifest_complete": True,
                  "topic_matches": classify(row, taxonomy, args.max_topics),
                  "candidate_categories": row.get("candidate_categories") or []}
        if args.openalex:
            if paper_id not in cache or cache[paper_id].get("status") in {
                "error", "temporary_error", "missing_title", "no_confident_match"
            }:
                try:
                    cache[paper_id] = openalex_match(row)
                except Exception as error:
                    cache[paper_id] = {"status": "temporary_error", "error_type": type(error).__name__,
                                       "error": str(error), "retryable": True}
                time.sleep(max(0.0, args.delay))
            record["openalex"] = cache[paper_id]
        records.append(record)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "papers.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    if args.openalex:
        cache_path.write_text("".join(json.dumps({"arxiv_id": key, "openalex": value}, ensure_ascii=False) + "\n" for key, value in sorted(cache.items())), encoding="utf-8")
    topic_counts = Counter(match["topic_id"] for row in records for match in row["topic_matches"])
    report = {"schema_version": "parsed_topic_manifest_v1", "paper_count": len(records), "max_topics_per_paper": args.max_topics,
              "papers_without_topic": sum(not row["topic_matches"] for row in records), "topic_counts": dict(topic_counts),
              "multi_topic_count": sum(len(row["topic_matches"]) > 1 for row in records)}
    if args.openalex:
        report["openalex"] = {"matched": sum(row.get("openalex", {}).get("status") == "matched" for row in records),
                              "not_indexed": sum(row.get("openalex", {}).get("status") == "not_indexed" for row in records),
                              "no_confident_match": sum(row.get("openalex", {}).get("status") == "no_confident_match" for row in records),
                              "temporary_errors": sum(row.get("openalex", {}).get("status") == "temporary_error" for row in records),
                              "errors": sum(row.get("openalex", {}).get("status") == "error" for row in records),
                              "with_references": sum(row.get("openalex", {}).get("reference_count", 0) > 0 for row in records)}
    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
