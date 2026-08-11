#!/usr/bin/env python3
"""Query OpenAlex for identity-resolved papers related to the topic taxonomy.

A candidate is retained when it has an OpenAlex ID, publication year >= the
configured cutoff, and a stable external identifier (DOI or arXiv ID). Results
are deduplicated across topics but preserve all matching topic IDs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

ARXIV_ID_RE = re.compile(r"^([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?$", re.I)
ARXIV_URL_RE = re.compile(r"arxiv(?:\.org/(?:abs|pdf)/|:)([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?", re.I)
USER_AGENT = "paper-graph-topic-seed-query/0.1 (mailto:paper-graph@example.org)"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def taxonomy_topics(path: Path) -> list[dict[str, Any]]:
    taxonomy = read_json(path)
    return [child for first in taxonomy.get("first_levels", []) for child in first.get("children", [])]


def normalize_doi(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text, flags=re.I)
    return text.lower() or None


def extract_arxiv(item: dict[str, Any]) -> str | None:
    ids = item.get("ids") or {}
    explicit = str(ids.get("arxiv") or "").strip()
    match = ARXIV_ID_RE.fullmatch(explicit)
    if match:
        return match.group(1)
    for value in [item.get("id"), item.get("primary_location", {}).get("landing_page_url")]:
        match = ARXIV_URL_RE.search(str(value or ""))
        if match:
            return match.group(1)
    return None


def stable_id(item: dict[str, Any]) -> tuple[str, str] | None:
    doi = normalize_doi(item.get("doi"))
    if doi:
        return "doi", doi
    arxiv = extract_arxiv(item)
    if arxiv:
        return "arxiv", arxiv
    return None


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def compact(item: dict[str, Any], topic: dict[str, Any]) -> dict[str, Any] | None:
    identity = stable_id(item)
    year = item.get("publication_year")
    if not item.get("id") or not isinstance(year, int) or not identity:
        return None
    openalex_id = str(item["id"]).rstrip("/").rsplit("/", 1)[-1]
    authors = [((a.get("author") or {}).get("display_name") or "") for a in item.get("authorships", [])]
    return {
        "paper_id": f"openalex:{openalex_id}",
        "openalex_id": f"openalex:{openalex_id}",
        "title": item.get("title") or "",
        "year": year,
        "authors": [a for a in authors if a],
        "doi": normalize_doi(item.get("doi")),
        "arxiv_id": extract_arxiv(item),
        "url": item.get("doi") or item.get("primary_location", {}).get("landing_page_url") or item.get("id"),
        "citation_count": int(item.get("cited_by_count") or 0),
        "identity_type": identity[0],
        "identity_value": identity[1],
        "topic_ids": [topic["id"]],
        "topic_labels": [topic.get("label") or topic["id"]],
        "matched_keywords": topic.get("keywords", []),
        "openalex_is_oa": bool((item.get("open_access") or {}).get("is_oa")),
    }


def merge(current: dict[str, Any], incoming: dict[str, Any]) -> None:
    current["topic_ids"] = sorted(set(current.get("topic_ids", [])) | set(incoming.get("topic_ids", [])))
    current["topic_labels"] = sorted(set(current.get("topic_labels", [])) | set(incoming.get("topic_labels", [])))
    current["matched_keywords"] = sorted(set(current.get("matched_keywords", [])) | set(incoming.get("matched_keywords", [])))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy", type=Path, default=Path("docs/generated/digest-topic-graphs/three-ai-v2/taxonomy.json"))
    parser.add_argument("--output", type=Path, default=Path("docs/generated/topic-seed-candidates-2016-v1.jsonl"))
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--min-year", type=int, default=2016)
    parser.add_argument("--per-topic", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--topic", default=None)
    args = parser.parse_args()
    if args.per_topic < 1 or args.min_year < 1900 or args.delay < 0:
        raise SystemExit("invalid min-year, per-topic, or delay")

    topics = taxonomy_topics(args.taxonomy)
    if args.topic:
        topics = [topic for topic in topics if topic.get("id") == args.topic]
    if not topics:
        raise SystemExit("no topics selected")

    cache_path = args.cache or args.output.with_suffix(".cache.json")
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    candidates: dict[str, dict[str, Any]] = {}
    failures = []
    for topic in topics:
        query = " OR ".join(f'"{keyword}"' for keyword in topic.get("keywords", []))
        url = ("https://api.openalex.org/works?search=" + quote(query)
               + f"&filter=from_publication_date:{args.min_year}-01-01&per-page={min(args.per_topic, 200)}")
        cache_key = hashlib.sha256(url.encode()).hexdigest()
        try:
            payload = cache.get(cache_key) or fetch_json(url, args.timeout)
            cache[cache_key] = payload
        except Exception as error:
            failures.append({"topic_id": topic.get("id"), "error": f"{type(error).__name__}: {error}"})
            continue
        for item in payload.get("results", []):
            candidate = compact(item, topic)
            if candidate is None:
                continue
            existing = candidates.get(candidate["paper_id"])
            if existing is None:
                candidates[candidate["paper_id"]] = candidate
            else:
                merge(existing, candidate)
        if args.delay:
            time.sleep(args.delay)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for candidate in sorted(candidates.values(), key=lambda x: (-x["year"], -x["citation_count"], x["paper_id"])):
            handle.write(json.dumps(candidate, ensure_ascii=False) + "\n")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    summary = {
        "taxonomy_topics": len(topics),
        "candidate_count": len(candidates),
        "topic_memberships": sum(len(c["topic_ids"]) for c in candidates.values()),
        "min_year": args.min_year,
        "stable_identity_rule": "doi_or_arxiv_id",
        "openalex_required": True,
        "failures": failures,
        "output": str(args.output),
    }
    args.output.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
