#!/usr/bin/env python3
"""Extract an auditable 85-keyword candidate set from OpenAlex Parquet shards."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb

from paper_graph.filter_profiles import FILTER_PROFILES, FilterProfile, get_filter_profile
from paper_graph.openalex_extraction import (
    EXTRACTION_SCHEMA_VERSION,
    canonical_hash,
    checkpoint_matches,
    file_sha256,
    load_checkpoints,
    shard_fingerprint,
    write_checkpoints,
    write_partitioned_products,
)
from paper_graph.openalex_snapshot import extract_arxiv_identity


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def author_rows(authorships: Any) -> list[dict[str, Any]]:
    rows = []
    for authorship in authorships or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        rows.append({
            "name": author.get("display_name") or authorship.get("raw_author_name"),
            "openalex_id": author.get("id"),
            "orcid": author.get("orcid") or authorship.get("raw_orcid"),
            "position": authorship.get("author_position"),
        })
    return rows


def compact(
    work: dict[str, Any], match: dict[str, Any], snapshot_date: str, profile: FilterProfile,
) -> dict[str, Any]:
    identity = extract_arxiv_identity(work)
    audit = profile.audit(work, match)
    status = audit.status
    value = profile.assess_value(work, audit)
    reasons = list(audit.reasons)
    openalex_id = str(work.get("id") or "").rsplit("/", 1)[-1]
    references = [str(value).rsplit("/", 1)[-1] for value in work.get("referenced_works") or []]
    return {
        "canonical_paper_id": f"arxiv:{identity.arxiv_id}" if identity else f"openalex:{openalex_id}",
        "openalex_id": openalex_id,
        "title": work.get("title") or work.get("display_name") or "",
        "authors": author_rows(work.get("authorships")),
        "publication_year": work.get("publication_year"),
        "publication_date": str(work.get("publication_date") or ""),
        "type": work.get("type"),
        "language": work.get("language"),
        "doi": work.get("doi"),
        "arxiv_id": identity.arxiv_id if identity else None,
        "arxiv_version": identity.version if identity else None,
        "identity_method": identity.method if identity else ("doi" if work.get("doi") else "openalex"),
        "identity_evidence": identity.evidence if identity else (work.get("doi") or work.get("id")),
        "identity_confidence": identity.confidence if identity else "exact",
        "primary_topic": work.get("primary_topic"),
        "topics": work.get("topics") or [],
        "keywords": work.get("keywords") or [],
        "concepts": work.get("concepts") or [],
        "abstract_inverted_index": work.get("abstract_inverted_index"),
        "referenced_works": references,
        "referenced_works_count": work.get("referenced_works_count") or len(references),
        "cited_by_count": work.get("cited_by_count") or 0,
        "open_access": work.get("open_access"),
        "has_content": work.get("has_content"),
        "has_fulltext": bool(work.get("has_fulltext")),
        "is_retracted": bool(work.get("is_retracted")),
        "is_paratext": bool(work.get("is_paratext")),
        "is_xpac": bool(work.get("is_xpac")),
        "quant_match": match,
        "finance_status": status,
        "finance_audit_reasons": reasons,
        "finance_audit_version": audit.audit_version,
        "finance_anchors": list(audit.finance_anchors),
        "finance_negative_contexts": list(audit.negative_contexts),
        "finance_acceptance_score": audit.acceptance_score,
        "finance_authored_match_fields": list(audit.authored_match_fields),
        "finance_review_priority": getattr(audit, "review_priority", "none"),
        "finance_review_priority_score": getattr(audit, "review_priority_score", 0),
        "research_value_tier": value.tier,
        "research_value_score": value.score,
        "research_value_reasons": list(value.reasons),
        "research_value_version": value.version,
        "graph_seed_eligible": status == "accepted" and value.tier in {"high", "medium"} and not any(
            bool(work.get(field)) for field in ("is_retracted", "is_paratext", "is_xpac")
        ) and bool(references or work.get("cited_by_count")),
        "digest_seed_eligible": status == "accepted" and value.tier in {"high", "medium"} and identity is not None,
        "snapshot_date": snapshot_date,
        "selection_version": profile.selection_version,
    }


def process_file(connection: duckdb.DuckDBPyConnection, path: Path, output: Path | None,
                 snapshot_date: str, min_year: int, batch_size: int,
                 profile: FilterProfile) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base_query = """
        SELECT id, title, display_name, abstract_inverted_index, keywords, topics, primary_topic
        FROM read_parquet(?)
        WHERE publication_year >= ?
    """
    cursor = connection.execute(base_query, [str(path), min_year])
    names = [item[0] for item in cursor.description]
    candidate_ids: list[str] = []
    match_by_id: dict[str, dict[str, Any]] = {}
    scanned = 0
    while True:
        batch = cursor.fetchmany(batch_size)
        if not batch:
            break
        for values in batch:
            work = dict(zip(names, values))
            scanned += 1
            match = profile.classify(work)
            if match["is_quant_candidate"]:
                ident = str(work["id"])
                candidate_ids.append(ident)
                match_by_id[ident] = match

    rows: list[dict[str, Any]] = []
    if candidate_ids:
        detailed = connection.execute(
            """
            SELECT
                id, title, display_name, authorships, publication_year,
                publication_date, type, language, doi, ids, primary_topic,
                topics, keywords, concepts, abstract_inverted_index,
                primary_location, best_oa_location, locations,
                referenced_works, referenced_works_count, cited_by_count,
                open_access, has_content, has_fulltext, is_retracted,
                is_paratext, is_xpac
            FROM read_parquet(?)
            WHERE id IN (SELECT unnest(?))
            """,
            [str(path), candidate_ids],
        )
        detail_names = [item[0] for item in detailed.description]
        for values in detailed.fetchall():
            work = dict(zip(detail_names, values))
            rows.append(compact(work, match_by_id[str(work["id"])], snapshot_date, profile))

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp-{os.getpid()}")
        with temporary.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        temporary.replace(output)
    summary = {
        "file": str(path), "scanned_post_min_year": scanned, "candidate_count": len(rows),
        "finance_status": dict(Counter(row["finance_status"] for row in rows)),
        "research_value_tier": dict(Counter(row["research_value_tier"] for row in rows)),
        "with_arxiv": sum(bool(row["arxiv_id"]) for row in rows),
        "graph_seed_eligible": sum(row["graph_seed_eligible"] for row in rows),
        "digest_seed_eligible": sum(row["digest_seed_eligible"] for row in rows),
    }
    return summary, rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--min-year", type=int, default=2016)
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--output-format", choices=("parquet", "jsonl", "both"), default="parquet")
    parser.add_argument(
        "--filter-profile", choices=tuple(FILTER_PROFILES), default="v4",
        help="Versioned filter profile; v4 is the frozen baseline for already-submitted jobs.",
    )
    parser.add_argument("--max-files", type=int, default=None, help="Optional cheap-probe limit after deterministic shard sorting.")
    args = parser.parse_args()
    profile = get_filter_profile(args.filter_profile)
    manifest = json.loads((args.input_root / "manifest.json").read_text(encoding="utf-8"))
    snapshot_date = str(manifest["date"])
    files = sorted(args.input_root.glob("updated_date=*/*.parquet"))
    if args.max_files is not None:
        if args.max_files < 1:
            raise SystemExit("--max-files must be at least 1")
        files = files[:args.max_files]
    if not files:
        raise SystemExit(f"no Parquet files under {args.input_root}")
    connection = duckdb.connect()
    connection.execute(f"SET threads={max(1, args.threads)}")
    checkpoint_path = args.output_root / "openalex_extract_checkpoints_v1.json"
    checkpoints = load_checkpoints(checkpoint_path)
    config_hash = canonical_hash({
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "snapshot_date": snapshot_date,
        "min_year": args.min_year,
        "batch_size": args.batch_size,
        "output_format": args.output_format,
        "selection_version": profile.selection_version,
        "finance_audit_version": profile.finance_audit_version,
        "research_value_version": profile.research_value_version,
    })
    summaries = []
    for path in files:
        relative = path.relative_to(args.input_root)
        source = shard_fingerprint(path, args.input_root)
        checkpoint = checkpoints["shards"].get(source["relative_path"])
        if checkpoint_matches(checkpoint, source=source, config_hash=config_hash):
            summary = dict(checkpoint["summary"])
            summaries.append(summary)
            print(json.dumps({**summary, "checkpoint_reused": True}, ensure_ascii=False), flush=True)
            continue
        output = (
            args.output_root / "legacy_jsonl" / relative.parent / f"{path.stem}.candidates.jsonl"
            if args.output_format in {"jsonl", "both"}
            else None
        )
        summary, rows = process_file(
            connection, path, output, snapshot_date, args.min_year, args.batch_size, profile
        )
        outputs = []
        if args.output_format in {"parquet", "both"}:
            outputs = write_partitioned_products(
                connection,
                rows,
                output_root=args.output_root,
                source_relative_path=relative,
            )
        if output is not None:
            outputs.append({
                "product": "legacy_jsonl",
                "path": str(output.resolve()),
                "row_count": len(rows),
                "content_length": output.stat().st_size,
                "sha256": file_sha256(output),
            })
        checkpoints["shards"][source["relative_path"]] = {
            "source": source,
            "config_hash": config_hash,
            "summary": summary,
            "outputs": outputs,
        }
        write_checkpoints(checkpoint_path, checkpoints)
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    total = {
        "snapshot_date": snapshot_date,
        "input_file_count": len(files),
        "scanned_post_min_year": sum(row["scanned_post_min_year"] for row in summaries),
        "candidate_count": sum(row["candidate_count"] for row in summaries),
        "finance_status": dict(sum((Counter(row["finance_status"]) for row in summaries), Counter())),
        "research_value_tier": dict(sum((Counter(row["research_value_tier"]) for row in summaries), Counter())),
        "with_arxiv": sum(row["with_arxiv"] for row in summaries),
        "graph_seed_eligible": sum(row["graph_seed_eligible"] for row in summaries),
        "digest_seed_eligible": sum(row["digest_seed_eligible"] for row in summaries),
        "selection_version": profile.selection_version,
        "finance_audit_version": profile.finance_audit_version,
        "research_value_version": profile.research_value_version,
        "extraction_schema_version": EXTRACTION_SCHEMA_VERSION,
        "config_hash": config_hash,
        "output_format": args.output_format,
    }
    write_json(args.output_root / "summary.json", total)
    print(json.dumps(total, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
