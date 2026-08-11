"""Checkpoint and partitioned-Parquet helpers for OpenAlex shard extraction."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

import duckdb


EXTRACTION_SCHEMA_VERSION = "openalex_partitioned_products_v2"
PRODUCT_SCHEMA_SUFFIX = "v2"
PRODUCT_NAMES = ("retrieval", "audit", "identity", "graph_seed", "digest_seed")


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def shard_fingerprint(path: Path, input_root: Path) -> dict[str, Any]:
    return {
        "relative_path": path.relative_to(input_root).as_posix(),
        "content_length": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def load_checkpoints(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "openalex_extract_checkpoints_v1", "shards": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "openalex_extract_checkpoints_v1":
        raise ValueError(f"unsupported checkpoint schema: {payload.get('schema_version')}")
    if not isinstance(payload.get("shards"), dict):
        raise ValueError("checkpoint shards must be an object")
    return payload


def write_checkpoints(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def checkpoint_matches(
    record: Mapping[str, Any] | None,
    *,
    source: Mapping[str, Any],
    config_hash: str,
) -> bool:
    if not record:
        return False
    if record.get("source") != dict(source) or record.get("config_hash") != config_hash:
        return False
    outputs = record.get("outputs")
    if not isinstance(outputs, list):
        return False
    for output in outputs:
        if not isinstance(output, Mapping):
            return False
        path_value = output.get("path")
        if path_value is None and output.get("row_count") == 0:
            continue
        path = Path(str(path_value))
        if not path.exists() or path.stat().st_size != output.get("content_length"):
            return False
        if file_sha256(path) != output.get("sha256"):
            return False
    return True


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _common(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "canonical_paper_id": row.get("canonical_paper_id"),
        "openalex_id": row.get("openalex_id"),
        "title": row.get("title"),
        "publication_year": row.get("publication_year"),
        "publication_date": row.get("publication_date"),
        "doi": row.get("doi"),
        "arxiv_id": row.get("arxiv_id"),
        "arxiv_version": row.get("arxiv_version"),
        "snapshot_date": row.get("snapshot_date"),
        "selection_version": row.get("selection_version"),
    }


def project_products(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    products = {name: [] for name in PRODUCT_NAMES}
    for row in rows:
        common = _common(row)
        retrieval = {
            **common,
            "authors_json": _json_text(row.get("authors") or []),
            "type": row.get("type"),
            "language": row.get("language"),
            "primary_topic_json": _json_text(row.get("primary_topic")),
            "topics_json": _json_text(row.get("topics") or []),
            "keywords_json": _json_text(row.get("keywords") or []),
            "concepts_json": _json_text(row.get("concepts") or []),
            "abstract_inverted_index_json": _json_text(row.get("abstract_inverted_index")),
            "referenced_works_json": _json_text(row.get("referenced_works") or []),
            "referenced_works_count": row.get("referenced_works_count"),
            "cited_by_count": row.get("cited_by_count"),
            "is_retracted": bool(row.get("is_retracted")),
            "is_paratext": bool(row.get("is_paratext")),
            "is_xpac": bool(row.get("is_xpac")),
            "quant_match_json": _json_text(row.get("quant_match") or {}),
        }
        audit = {
            **common,
            "finance_status": row.get("finance_status"),
            "finance_audit_version": row.get("finance_audit_version"),
            "finance_audit_reasons_json": _json_text(row.get("finance_audit_reasons") or []),
            "finance_anchors_json": _json_text(row.get("finance_anchors") or []),
            "finance_negative_contexts_json": _json_text(row.get("finance_negative_contexts") or []),
            "finance_acceptance_score": row.get("finance_acceptance_score"),
            "finance_authored_match_fields_json": _json_text(row.get("finance_authored_match_fields") or []),
            "research_value_tier": row.get("research_value_tier"),
            "research_value_score": row.get("research_value_score"),
            "research_value_reasons_json": _json_text(row.get("research_value_reasons") or []),
            "research_value_version": row.get("research_value_version"),
        }
        identity = {
            **common,
            "identity_method": row.get("identity_method"),
            "identity_evidence": row.get("identity_evidence"),
            "identity_confidence": row.get("identity_confidence"),
        }
        products["retrieval"].append(retrieval)
        products["audit"].append(audit)
        products["identity"].append(identity)
        if row.get("graph_seed_eligible"):
            products["graph_seed"].append({**common, "seed_type": "graph"})
        if row.get("digest_seed_eligible"):
            products["digest_seed"].append({**common, "seed_type": "digest"})
    return products


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _write_rows_parquet(
    connection: duckdb.DuckDBPyConnection, rows: list[dict[str, Any]], output: Path
) -> dict[str, Any]:
    if not rows:
        return {"path": None, "row_count": 0, "content_length": 0, "sha256": None}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_json = output.with_name(f".{output.name}.rows-{os.getpid()}.jsonl")
    temporary_parquet = output.with_name(f".{output.name}.tmp-{os.getpid()}")
    try:
        with temporary_json.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(_json_text(row) + "\n")
        connection.execute(
            f"COPY (SELECT * FROM read_json_auto('{_sql_path(temporary_json)}', format='newline_delimited')) "
            f"TO '{_sql_path(temporary_parquet)}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        temporary_parquet.replace(output)
    finally:
        temporary_json.unlink(missing_ok=True)
        temporary_parquet.unlink(missing_ok=True)
    return {
        "path": str(output.resolve()),
        "row_count": len(rows),
        "content_length": output.stat().st_size,
        "sha256": file_sha256(output),
    }


def write_partitioned_products(
    connection: duckdb.DuckDBPyConnection,
    rows: Iterable[Mapping[str, Any]],
    *,
    output_root: Path,
    source_relative_path: Path,
) -> list[dict[str, Any]]:
    products = project_products(rows)
    partition = source_relative_path.parent
    stem = source_relative_path.stem
    outputs: list[dict[str, Any]] = []
    for product_name in PRODUCT_NAMES:
        output = output_root / f"openalex_{product_name}_{PRODUCT_SCHEMA_SUFFIX}" / partition / f"{stem}.parquet"
        metadata = _write_rows_parquet(connection, products[product_name], output)
        outputs.append({"product": product_name, **metadata})
    return outputs


__all__ = [
    "EXTRACTION_SCHEMA_VERSION",
    "PRODUCT_NAMES",
    "PRODUCT_SCHEMA_SUFFIX",
    "canonical_hash",
    "checkpoint_matches",
    "file_sha256",
    "load_checkpoints",
    "project_products",
    "shard_fingerprint",
    "write_checkpoints",
    "write_partitioned_products",
]
