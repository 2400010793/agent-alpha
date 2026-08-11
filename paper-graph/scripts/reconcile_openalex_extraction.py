#!/usr/bin/env python3
"""Reconcile partitioned OpenAlex products against the extraction summary."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import duckdb

from paper_graph.openalex_extraction import PRODUCT_NAMES, PRODUCT_SCHEMA_SUFFIX


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _paths(root: Path, product: str) -> list[str]:
    return [str(path) for path in sorted((root / f"openalex_{product}_{PRODUCT_SCHEMA_SUFFIX}").glob("updated_date=*/*.parquet"))]


def _count(connection: duckdb.DuckDBPyConnection, paths: list[str]) -> int:
    if not paths:
        return 0
    return int(connection.execute("SELECT count(*) FROM read_parquet(?)", [paths]).fetchone()[0])


def _difference_count(
    connection: duckdb.DuckDBPyConnection, left: list[str], right: list[str]
) -> int:
    if not left:
        return 0
    if not right:
        return _count(connection, left)
    return int(connection.execute(
        "SELECT count(*) FROM (SELECT canonical_paper_id FROM read_parquet(?) EXCEPT SELECT canonical_paper_id FROM read_parquet(?))",
        [left, right],
    ).fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-retrieval-count", type=int)
    parser.add_argument("--expected-input-files", type=int)
    args = parser.parse_args()

    summary = json.loads((args.output_root / "summary.json").read_text(encoding="utf-8"))
    connection = duckdb.connect()
    paths = {product: _paths(args.output_root, product) for product in PRODUCT_NAMES}
    counts = {product: _count(connection, values) for product, values in paths.items()}
    retrieval = paths["retrieval"]
    errors: list[str] = []
    expected_candidates = int(summary["candidate_count"])
    for product in ("retrieval", "audit", "identity"):
        if counts[product] != expected_candidates:
            errors.append(f"{product}_count={counts[product]} expected={expected_candidates}")
    for product in ("audit", "identity", "graph_seed", "digest_seed"):
        missing = _difference_count(connection, paths[product], retrieval)
        if missing:
            errors.append(f"{product}_outside_retrieval={missing}")
    if counts["graph_seed"] != int(summary["graph_seed_eligible"]):
        errors.append("graph_seed count disagrees with summary")
    if counts["digest_seed"] != int(summary["digest_seed_eligible"]):
        errors.append("digest_seed count disagrees with summary")
    if args.expected_retrieval_count is not None and counts["retrieval"] != args.expected_retrieval_count:
        errors.append(f"retrieval_count={counts['retrieval']} expected_argument={args.expected_retrieval_count}")
    if args.expected_input_files is not None and int(summary["input_file_count"]) != args.expected_input_files:
        errors.append(f"input_file_count={summary['input_file_count']} expected_argument={args.expected_input_files}")
    distinct = 0
    if retrieval:
        distinct = int(connection.execute(
            "SELECT count(DISTINCT openalex_id) FROM read_parquet(?)", [retrieval]
        ).fetchone()[0])
        if distinct != counts["retrieval"]:
            errors.append(f"unique_openalex_ids={distinct} retrieval_count={counts['retrieval']}")

    result = {
        "schema_version": "openalex_extraction_reconciliation_v1",
        "status": "ok" if not errors else "failed",
        "output_root": str(args.output_root.resolve()),
        "input_file_count": summary["input_file_count"],
        "counts": counts,
        "unique_openalex_id_count": distinct,
        "errors": errors,
    }
    _write_json(args.output_root / "reconciliation.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
