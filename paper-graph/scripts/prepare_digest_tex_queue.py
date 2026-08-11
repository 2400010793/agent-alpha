#!/usr/bin/env python3
"""Select high-priority papers for Paper Digest TeX processing.

This script reads the already-built de-duplicated queue only. It never builds,
changes, or rewrites a graph. By default it creates a manifest and a dry-run
list; pass --download to fetch arXiv source packages into an isolated cache.
"""
from __future__ import annotations

import argparse
import json
import re
import tarfile
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


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


def arxiv_id(row: dict[str, Any]) -> str | None:
    value = str(row.get("arxiv_id") or row.get("paper_id") or "").strip()
    value = re.sub(r"^arxiv:", "", value, flags=re.I).split("v", 1)[0]
    return value or None


def select(rows: list[dict[str, Any]], minimum_priority: float, limit: int) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        paper = arxiv_id(row)
        if not paper or row.get("digest_status") not in {None, "pending", "retry", "failed"}:
            continue
        priority = float((row.get("importance") or {}).get("digest_priority") or 0.0)
        if priority >= minimum_priority:
            selected.append({
                "paper_id": row.get("paper_id") or f"arxiv:{paper}",
                "arxiv_id": paper,
                "title": row.get("title") or "",
                "topic_ids": row.get("topic_ids", []),
                "variant_ids": row.get("variant_ids", []),
                "membership_count": row.get("membership_count", 0),
                "importance": row.get("importance", {}),
                "digest_priority": priority,
                "digest_rank": row.get("digest_rank"),
                "tex_status": "selected",
                "seed_eligible": False,
                "reason": "high_digest_priority",
            })
    selected.sort(key=lambda row: (-row["digest_priority"], str(row["paper_id"])))
    return selected[:limit] if limit > 0 else selected


def download_source(paper: dict[str, Any], download_dir: Path) -> dict[str, Any]:
    paper_id = paper["arxiv_id"]
    target = download_dir / f"{paper_id.replace('/', '_')}.tar"
    if target.exists() and target.stat().st_size > 0:
        paper.update({"tex_status": "downloaded", "source_path": str(target), "downloaded": False})
        return paper
    request = Request(f"https://export.arxiv.org/e-print/{paper_id}", headers={"User-Agent": "paper-graph/0.1"})
    download_dir.mkdir(parents=True, exist_ok=True)
    with urlopen(request, timeout=60) as response, target.open("wb") as handle:
        handle.write(response.read())
    paper.update({"tex_status": "downloaded", "source_path": str(target), "downloaded": True})
    return paper


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=Path("docs/generated/digest-topic-graphs/three-ai-v2/digest_graph_queue.jsonl"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--minimum-priority", type=float, default=0.65)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--download-dir", type=Path, default=Path("docs/generated/digest-topic-graphs/three-ai-v2/tex-source-cache"))
    args = parser.parse_args()
    output = args.output or args.queue.with_name("digest_tex_queue.jsonl")
    selected = select(read_jsonl(args.queue), args.minimum_priority, args.limit)
    if args.download:
        for paper in selected:
            try:
                download_source(paper, args.download_dir)
            except Exception as error:
                paper.update({"tex_status": "download_failed", "error": f"{type(error).__name__}: {error}"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected), encoding="utf-8")
    summary = {"selected_count": len(selected), "minimum_priority": args.minimum_priority,
               "download_requested": args.download, "downloaded_count": sum(row["tex_status"] == "downloaded" for row in selected),
               "seed_eligible_count": 0, "graphs_modified": False, "output": str(output)}
    output.with_name("digest_tex_queue_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
