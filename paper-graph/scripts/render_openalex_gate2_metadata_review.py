#!/usr/bin/env python3
"""Render the fixed Gate 2 review sample with local OpenAlex abstracts and keywords."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paper_graph.openalex_snapshot import reconstruct_abstract


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data/processed/openalex_quant_gate2_v1/review_sample.jsonl"
SOURCE_ROOT = ROOT / "data/processed/openalex_quant_sample"
OUTPUT = ROOT / "data/processed/openalex_quant_gate2_v1/review_sample_metadata.md"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def keyword_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item["display_name"]) for item in value if isinstance(item, dict) and item.get("display_name")]


def load_source_rows(ids: set[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(SOURCE_ROOT.glob("updated_date=*/*.candidates.jsonl")):
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                row = json.loads(line)
                if row.get("openalex_id") in ids:
                    found[row["openalex_id"]] = row
    return found


def md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def main() -> None:
    sample = read_jsonl(SAMPLE)
    source = load_source_rows({row["openalex_id"] for row in sample})
    missing = sorted({row["openalex_id"] for row in sample} - source.keys())
    if missing:
        raise SystemExit(f"missing local OpenAlex rows: {', '.join(missing)}")

    lines = [
        "# OpenAlex Gate 2 review sample：摘要与关键词",
        "",
        "本表按固定 180 篇人工复核样本生成。摘要和关键词均来自本地 OpenAlex Work 记录；关键词是 OpenAlex 机器抽取关键词，不等同于论文作者关键词。`—` 表示 OpenAlex 未提供摘要或关键词。",
        "",
        "| # | OpenAlex | 自动状态 | 标题 | 摘要 | OpenAlex keywords |",
        "|---:|---|---|---|---|---|",
    ]
    for number, review_row in enumerate(sample, 1):
        row = source[review_row["openalex_id"]]
        abstract = reconstruct_abstract(row.get("abstract_inverted_index")) or "—"
        keywords = "; ".join(keyword_names(row.get("keywords"))) or "—"
        lines.append("| " + " | ".join([
            str(number),
            md(review_row["openalex_id"]),
            md(review_row["automatic_finance_status"]),
            md(review_row["title"]),
            md(abstract),
            md(keywords),
        ]) + " |")

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "rows": len(sample), "output": str(OUTPUT), "missing_abstracts": sum(not reconstruct_abstract(source[row["openalex_id"]].get("abstract_inverted_index")) for row in sample)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
