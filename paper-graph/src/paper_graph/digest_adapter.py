"""Read the structured Opinion Digest archives as Paper Graph records."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "；".join(item for item in (_text(v) for v in value) if item)
    if isinstance(value, dict):
        return "；".join(f"{key}: {_text(item)}" for key, item in value.items() if _text(item))
    return str(value).strip() if value is not None else ""


def _year(arxiv_id: str) -> int | None:
    match = re.match(r"^(\d{2})(\d{2})\.", arxiv_id)
    if not match:
        return None
    return 2000 + int(match.group(1)) if int(match.group(1)) < 90 else 1900 + int(match.group(1))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("arxiv_id"):
                rows.append(row)
    return rows


def _to_paper(row: dict[str, Any]) -> dict[str, Any] | None:
    arxiv_id = str(row.get("arxiv_id", "")).strip()
    if not arxiv_id or row.get("status") == "failed":
        return None
    analysis = row.get("article_opinions") if isinstance(row.get("article_opinions"), dict) else {}
    summary = analysis.get("structured_summary") if isinstance(analysis.get("structured_summary"), dict) else {}
    reading_note = row.get("llm_reading_note") if isinstance(row.get("llm_reading_note"), dict) else {}
    opinions = [item for item in analysis.get("article_opinions", []) if isinstance(item, dict)]
    title = _text(row.get("title")) or f"arXiv {arxiv_id}"
    digest_fields = {
        "research_topic": _text(reading_note.get("research_topic_category") or row.get("research_topic_category") or analysis.get("opinion_category") or reading_note.get("opinion_category")),
        "research_question": _text(summary.get("problem") or reading_note.get("problem")),
        "method": _text(summary.get("method") or reading_note.get("method_logic")),
        "author_claim": _text(summary.get("author_claim") or reading_note.get("central_claim")),
        "evidence_status": _text(summary.get("evidence_status")),
        "limitations": _text(summary.get("limitations") or reading_note.get("limitations")),
        "critical_assessment": _text(summary.get("critical_assessment")),
        "missing_validation": _text(summary.get("missing_tests") or reading_note.get("not_disclosed")),
        "datasets": _text(summary.get("datasets") or reading_note.get("datasets_and_sample_split")),
        "metrics": _text(summary.get("metrics_explained") or reading_note.get("metrics")),
        "experiment_details": _text(summary.get("experiment_details") or reading_note.get("experimental_setup")),
        "plain_language_takeaway": _text(summary.get("plain_language_takeaway") or analysis.get("plain_language_takeaway")),
        "opinions": opinions,
        "analysis_pipeline": _text(row.get("analysis_pipeline")),
        "analysis_agent": _text(analysis.get("analysis_agent") or row.get("analysis_agent")),
        "faithfulness_verdict": _text(row.get("faithfulness_verdict")),
        "recommendation_score": analysis.get("recommendation_score") or row.get("reading_recommendation_score"),
    }
    abstract = (digest_fields["plain_language_takeaway"]
                or digest_fields["research_question"]
                or digest_fields["method"]
                or _text(row.get("summary")))
    raw_authors = row.get("authors") or row.get("author") or []
    authors = ([str(item.get("name") or item.get("author", "")) for item in raw_authors
                if isinstance(item, dict)]
               if isinstance(raw_authors, list) else [str(raw_authors)])
    return {
        "id": arxiv_id,
        "title": title,
        "authors": [author for author in authors if author],
        "year": _year(arxiv_id),
        "citation_count": 0,
        "global_impact": 0.0,
        "abstract": abstract,
        "keywords": [digest_fields["research_topic"]] if digest_fields["research_topic"] else [],
        "url": _text(row.get("url")) or f"https://arxiv.org/abs/{arxiv_id}",
        "metadata": {"digest": digest_fields},
    }


def load_digest_papers(root: str | Path) -> list[dict[str, Any]]:
    """Load and de-duplicate the same archives used by opinion_digest.html."""
    base = Path(root)
    paths = (
        base / "data/opinion_analysis_archive.jsonl",
        base / "data/opinion_batch_analysis_gpt54mini_20260724.jsonl",
        base / "data/arxiv_tex_three_ai_analysis.jsonl",
    )
    merged: dict[str, dict[str, Any]] = {}
    for path in paths:
        for row in _read_jsonl(path):
            model = _text(row.get("model") or row.get("analysis_agent") or (row.get("article_opinions") or {}).get("analysis_agent"))
            if model and not ("gpt-5.4-mini" in model or "gpt-5-mini" in model):
                continue
            paper = _to_paper(row)
            if paper:
                merged[paper["id"]] = paper
    return list(merged.values())
