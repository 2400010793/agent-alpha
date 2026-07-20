from __future__ import annotations

import json
from pathlib import Path


def write_review_report(path: str | Path, review: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".json":
        out.write_text(json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return
    factor_id = review.get("factor_id") or "unknown"
    required_revisions = review.get("required_revisions") or []
    revision_text = "\n".join(f"- {item}" for item in required_revisions) if required_revisions else "- None"
    text = f"""# Factor Review: {factor_id}

Decision: {review.get("decision", "unknown")}

## Statistical Summary
{review.get("statistical_summary", "")}

## Implementation Summary
{review.get("implementation_quality_summary", "")}

## Economic Logic
{review.get("economic_logic_summary", "")}

## Risk Summary
{review.get("risk_summary", "")}

## Required Revisions
{revision_text}
"""
    out.write_text(text, encoding="utf-8")