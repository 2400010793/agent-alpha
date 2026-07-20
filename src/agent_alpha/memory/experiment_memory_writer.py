from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from agent_alpha.evaluation.evaluation_schema import utc_now_iso
from agent_alpha.memory.feedback_memory import DEFAULT_FEEDBACK_MEMORY_PATH


def _feedback_label(decision: str) -> str:
    return {"accept": "GOOD", "reject": "BAD", "revise": "REVISE"}.get(decision, "REVISE")


def _avoid_rule(failure_modes: list[str]) -> str:
    if "field_leakage" in failure_modes:
        return "Avoid label leakage or blocked evaluation fields in factor expressions."
    if "compile_failed" in failure_modes:
        return "Avoid rendered factors that do not pass Python compilation."
    if "missing_factor_file" in failure_modes:
        return "Avoid treating candidates as evaluable before a factor file is rendered."
    if any("zero_ratio" in mode or "finite_ratio" in mode for mode in failure_modes):
        return "Avoid sparse, mostly zero, or non-finite factor outputs."
    if any("rankic" in mode for mode in failure_modes):
        return "Avoid weak RankIC under the current evaluation thresholds."
    return ""


def build_feedback_memory(review: dict, candidate: dict | None = None) -> dict:
    candidate = candidate or {}
    decision = str(review.get("decision") or "revise")
    label = _feedback_label(decision)
    failure_modes = [str(x) for x in review.get("failure_modes", [])]
    required_revisions = [str(x) for x in review.get("required_revisions", [])]
    reason = str(
        review.get("implementation_quality_summary")
        or review.get("statistical_summary")
        or review.get("risk_summary")
        or review.get("economic_logic_summary")
        or decision
    )
    return {
        "schema_version": "feedback_memory_record_v1",
        "feedback_id": uuid.uuid4().hex,
        "factor_id": str(review.get("factor_id") or candidate.get("factor_id") or candidate.get("name") or ""),
        "label": label,
        "reason": reason,
        "reusable_principle": "Mechanism + expression + metric worked under current thresholds." if label == "GOOD" else "",
        "avoid_rule": _avoid_rule(failure_modes) if label == "BAD" else "",
        "suggested_next_action": "; ".join(required_revisions) if label == "REVISE" else "",
        "mechanism_tags": list(candidate.get("mechanism_tags") or candidate.get("hf_mechanism_tags") or []),
        "prefix_expression": candidate.get("prefix_expression"),
        "metrics": dict(review.get("metrics") or {}),
        "failure_modes": failure_modes,
        "required_revisions": required_revisions,
        "created_at": utc_now_iso(),
    }


def write_feedback_memory(path: str | Path, records: list[dict]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def append_feedback_memory(evaluation: dict[str, Any], path: str | Path = DEFAULT_FEEDBACK_MEMORY_PATH) -> dict[str, Any]:
    record = build_feedback_memory(evaluation)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return record