#!/usr/bin/env python3
"""Write deterministic Graph and Digest seed manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from paper_graph.seed_selection import SEED_SELECTION_VERSION, select_seed_manifests


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--graph-target", type=int, default=30)
    parser.add_argument("--digest-target", type=int, default=5)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.candidates.read_text(encoding="utf-8").splitlines() if line.strip()]
    graph, digest = select_seed_manifests(
        rows, graph_target=args.graph_target, digest_target=args.digest_target
    )
    graph_path = args.output_root / "graph_seed_manifest.jsonl"
    digest_path = args.output_root / "digest_seed_manifest.jsonl"
    _write_jsonl(graph_path, graph)
    _write_jsonl(digest_path, digest)
    summary = {
        "schema_version": "openalex_seed_summary_v1",
        "selection_version": SEED_SELECTION_VERSION,
        "candidate_count": len(rows),
        "graph_seed_count": len(graph),
        "graph_approved_count": sum(row["selection_status"] == "approved" for row in graph),
        "graph_expansion_count": sum(row["selection_status"] == "expansion_candidate" for row in graph),
        "digest_seed_count": len(digest),
        "digest_approved_count": sum(row["selection_status"] == "approved" for row in digest),
        "digest_expansion_count": sum(row["selection_status"] == "expansion_candidate" for row in digest),
    }
    summary_path = args.output_root / "summary.json"
    _write_json(summary_path, summary)
    _write_json(args.output_root / "manifest.json", {
        "schema_version": "openalex_seed_artifact_manifest_v1",
        "selection_version": SEED_SELECTION_VERSION,
        "input": {"path": str(args.candidates.resolve()), "sha256": _sha(args.candidates)},
        "outputs": [
            {"path": str(graph_path.resolve()), "sha256": _sha(graph_path), "row_count": len(graph)},
            {"path": str(digest_path.resolve()), "sha256": _sha(digest_path), "row_count": len(digest)},
            {"path": str(summary_path.resolve()), "sha256": _sha(summary_path)},
        ],
    })
    print(json.dumps({"status": "ok", **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
