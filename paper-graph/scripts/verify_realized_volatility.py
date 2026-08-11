"""Build a small, auditable Realized Volatility citation fixture.

This script never invents edges: a CITES edge is emitted only when OpenAlex
explicitly lists the target work in the source work's ``referenced_works``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from paper_graph.open_academic import OpenAcademicClient
from paper_graph.verification import verified_reference_edges


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="realized volatility")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("outputs/realized-volatility-verification"))
    args = parser.parse_args()
    client = OpenAcademicClient(timeout=20)
    candidates = client.openalex_search(args.query, args.limit)
    papers = []
    failures = []
    for candidate in candidates:
        try:
            papers.append(client.openalex_work(candidate["id"]))
        except Exception as error:  # retain an auditable failure record
            failures.append({"id": candidate.get("id"), "error": str(error)})
    edges = verified_reference_edges(papers)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, rows in (("papers.jsonl", papers), ("verified_edges.jsonl", [edge.__dict__ for edge in edges]), ("failures.jsonl", failures)):
        with (args.output / name).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {
        "query": args.query,
        "candidate_count": len(candidates),
        "verified_paper_count": len(papers),
        "verified_direct_citation_count": len(edges),
        "failed_count": len(failures),
        "provider": "openalex",
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())