from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_alpha.agents.prompt_registry import prompt_paths_for_tags
from agent_alpha.config import PROJECT_ROOT
from agent_alpha.memory.feedback_memory import DEFAULT_FEEDBACK_MEMORY_PATH, load_feedback_records, search_feedback_records
from agent_alpha.skills.skill_loader import load_skill


SHARED_PROMPT_FILES_BY_TASK = {
    "paper_to_signal": (
        "prompts/shared/hf_field_constraints.md",
    ),
    "signal_to_factor": (
        "prompts/shared/hf_field_constraints.md",
        "prompts/shared/hf_factor_requirements.md",
        "prompts/shared/asl_factor_candidate_output.md",
    ),
    "factor_evaluation": (
        "prompts/shared/hf_field_constraints.md",
        "prompts/shared/hf_factor_requirements.md",
    ),
}

SKILL_FILES = {
    "paper_to_signal": "skills/paper_to_signal/SKILL.md",
    "signal_to_factor": "skills/signal_to_factor/SKILL.md",
    "factor_candidate_format_checker": "skills/factor_candidate_format_checker/SKILL.md",
    "supported_fields_and_asl": "skills/supported_fields_and_asl/SKILL.md",
    "signal_format_checker": "skills/signal_format_checker/SKILL.md",
    "factor_evaluation": "skills/factor_evaluation/SKILL.md",
    "memory_absorption": "skills/memory_absorption/SKILL.md",
    "mutation_memory": "skills/mutation_memory/SKILL.md",
}


def _project_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else PROJECT_ROOT / value


def _read_optional_text(path: str | Path) -> str:
    resolved = _project_path(path)
    return resolved.read_text(encoding="utf-8") if resolved.exists() else ""


def load_shared_constraints(paths: tuple[str, ...] | None = None, *, task: str = "") -> dict[str, str]:
    if paths is None:
        paths = SHARED_PROMPT_FILES_BY_TASK.get(task, ("prompts/shared/hf_field_constraints.md",))
    return {Path(path).name: text for path in paths if (text := _read_optional_text(path))}


def load_skill_rules(skill_name: str) -> str:
    path = SKILL_FILES.get(skill_name)
    if not path:
        return ""
    resolved = _project_path(path)
    if not resolved.exists():
        return ""
    return load_skill(resolved).text


def load_mechanism_prompt_context(tags: list[str]) -> list[dict[str, str]]:
    prompts: list[dict[str, str]] = []
    for path in prompt_paths_for_tags(tags):
        text = path.read_text(encoding="utf-8")
        prompts.append({"path": str(path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path), "text": text})
    return prompts


def _compact_feedback_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": str(record.get("label") or "").upper(),
        "factor_id": str(record.get("factor_id") or record.get("name") or ""),
        "failure_type": str(record.get("failure_type") or ""),
        "good_pattern": str(record.get("good_pattern") or record.get("reusable_principle") or ""),
        "avoid_rule": str(record.get("avoid_rule") or ""),
        "repair_hint": str(record.get("repair_hint") or ""),
        "summary": str(record.get("summary") or record.get("reason") or ""),
    }


def load_good_bad_memory(
    query: str = "",
    *,
    feedback_path: str | Path = DEFAULT_FEEDBACK_MEMORY_PATH,
    limit: int = 12,
) -> dict[str, Any]:
    raw_records = search_feedback_records(query, feedback_path, limit=limit) if query else []
    if not raw_records:
        raw_records = load_feedback_records(feedback_path, limit=limit)
    records = [_compact_feedback_record(record) for record in raw_records]
    good = [record for record in records if record["label"] == "GOOD"]
    bad = [record for record in records if record["label"] == "BAD"]
    revise = [record for record in records if record["label"] == "REVISE"]
    return {
        "records": records,
        "reuse_principles": [record["good_pattern"] or record["summary"] for record in good if record["good_pattern"] or record["summary"]],
        "avoid_rules": [record["avoid_rule"] or record["summary"] for record in bad if record["avoid_rule"] or record["summary"]],
        "repair_hints": [record["repair_hint"] or record["summary"] for record in revise if record["repair_hint"] or record["summary"]],
    }


def build_prompt_context(
    *,
    task: str,
    skill_name: str,
    mechanism_tags: list[str] | None = None,
    memory_query: str = "",
    feedback_path: str | Path = DEFAULT_FEEDBACK_MEMORY_PATH,
    feedback_limit: int = 12,
) -> dict[str, Any]:
    tags = mechanism_tags or []
    return {
        "task": task,
        "skill_rules": load_skill_rules(skill_name),
        "factor_candidate_format_checker": load_skill_rules("factor_candidate_format_checker") if task in {"signal_to_factor", "factor_mutation"} else "",
        "supported_fields_and_asl": load_skill_rules("supported_fields_and_asl") if task in {"signal_to_factor", "factor_mutation"} else "",
        "mutation_memory": load_skill_rules("mutation_memory") if task == "factor_mutation" else "",
        "signal_format_checker": load_skill_rules("signal_format_checker") if task == "signal_mutation" else "",
        "shared_constraints": load_shared_constraints(task=task),
        "mechanism_prompts": load_mechanism_prompt_context(tags),
        "good_bad_memory": load_good_bad_memory(memory_query, feedback_path=feedback_path, limit=feedback_limit),
    }


__all__ = ["build_prompt_context", "load_good_bad_memory", "load_shared_constraints", "load_skill_rules"]