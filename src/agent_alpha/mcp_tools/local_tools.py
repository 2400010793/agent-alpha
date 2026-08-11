from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from agent_alpha.factors.field_guard import validate_factor_expression
from agent_alpha.factors.fac_eval_adapter import write_fac_eval_config
from agent_alpha.factors.fac_eval_adapter import py_compile_factor_file
from agent_alpha.factors.factor_file_renderer import render_factor_file
from agent_alpha.factors.llm_candidate_guard import qualify_factor_candidate_payload
from agent_alpha.memory.function_memory import search_function_memory
from agent_alpha.memory.specialist_memory import search_specialist_memory
from agent_alpha.memory.transfer_memory import search_transfer_memory
from agent_alpha.rag.alpha_memory_retriever import search_similar_alphas
from agent_alpha.rag.field_retriever import recommend_fields_for_signal
from agent_alpha.rag.field_registry import FieldRegistry
from agent_alpha.search.mutation_controller import select_mutation_plan


def list_fields(_: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = FieldRegistry.from_yaml()
    return {
        "allowed_input_fields": sorted(registry.allowed_input_fields),
        "derived_feature_fields": sorted(registry.derived_feature_fields),
        "label_fields": sorted(registry.label_fields),
        "blocked_fields": sorted(registry.blocked_fields),
        "allowed_functions": sorted(registry.allowed_functions),
    }


def validate_factor_fields(query: dict[str, Any]) -> dict[str, Any]:
    expression = str(query.get("expression") or "")
    result = validate_factor_expression(expression, FieldRegistry.from_yaml())
    return result.__dict__


def recommend_fields_tool(query: dict[str, Any]) -> dict[str, Any]:
    signal = query.get("signal")
    if not isinstance(signal, dict):
        raise ValueError("signal must be a mapping")
    return recommend_fields_for_signal(signal, limit=int(query.get("limit", 20)), runtime_safe_only=bool(query.get("runtime_safe_only", True)))


def validate_factor_candidate_tool(query: dict[str, Any]) -> dict[str, Any]:
    candidate = query.get("candidate")
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be a mapping")
    qualification = qualify_factor_candidate_payload(candidate)
    return {"ok": qualification.ok, "message": qualification.message, "candidate": qualification.candidate}


def render_and_compile_candidate_tool(query: dict[str, Any]) -> dict[str, Any]:
    candidate = query.get("candidate")
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be a mapping")
    qualification = qualify_factor_candidate_payload(candidate)
    if not qualification.ok:
        return {"ok": False, "stage": "validate", "message": qualification.message, "candidate": qualification.candidate}
    output_dir = query.get("output_dir")
    if output_dir:
        factor_file = render_factor_file(qualification.candidate or {}, output_dir=str(output_dir))
        compile_result = py_compile_factor_file(factor_file)
        return {
            "ok": compile_result.returncode == 0,
            "stage": "compile" if compile_result.returncode else "ok",
            "message": compile_result.stderr if compile_result.returncode else "ok",
            "candidate": qualification.candidate,
            "factor_file": str(factor_file),
            "compile_returncode": compile_result.returncode,
            "compile_stderr": compile_result.stderr,
        }
    with tempfile.TemporaryDirectory(prefix="agent_alpha_mcp_factor_") as tmpdir:
        factor_file = render_factor_file(qualification.candidate or {}, output_dir=tmpdir)
        compile_result = py_compile_factor_file(factor_file)
        return {
            "ok": compile_result.returncode == 0,
            "stage": "compile" if compile_result.returncode else "ok",
            "message": compile_result.stderr if compile_result.returncode else "ok",
            "candidate": qualification.candidate,
            "factor_file": str(factor_file),
            "compile_returncode": compile_result.returncode,
            "compile_stderr": compile_result.stderr,
        }


def render_fac_eval_file(query: dict[str, Any]) -> dict[str, Any]:
    candidate = query.get("candidate")
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be a mapping")
    output_dir = str(query.get("output_dir") or "data/factors/rendered")
    path = render_factor_file(candidate, output_dir=output_dir)
    return {"path": str(path)}


def write_fac_eval_config_tool(query: dict[str, Any]) -> dict[str, Any]:
    factor_files = query.get("factor_files")
    if not isinstance(factor_files, list):
        raise ValueError("factor_files must be a list")
    output_path = str(query.get("output_path") or "outputs/factor_runs/fac_eval_config.yaml")
    path = write_fac_eval_config(factor_files, output_path)
    return {"path": str(path)}


def search_jsonl(path: str | Path, query_text: str, limit: int = 10) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    query_lower = query_text.casefold()
    rows: list[dict[str, Any]] = []
    for line in file_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if query_lower in json.dumps(row, ensure_ascii=False).casefold():
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def search_specialist_agent_memory(query: dict[str, Any]) -> dict[str, Any]:
    agent_name = str(query.get("agent_name") or "")
    if not agent_name:
        raise ValueError("agent_name is required")
    query_text = str(query.get("query") or "")
    root = query.get("root") or "data/memory/cog/specialist_agents"
    limit = int(query.get("limit", 5))
    records = search_specialist_memory(agent_name, query_text, root=root, limit=limit)
    return {"agent_name": agent_name, "query": query_text, "records": records}


def search_function_memory_tool(query: dict[str, Any]) -> dict[str, Any]:
    query_text = str(query.get("query") or "")
    path = query.get("path") or "data/memory/cog/function_memory.jsonl"
    limit = int(query.get("limit", 5))
    records = search_function_memory(query_text, path=path, limit=limit)
    return {"query": query_text, "records": records}


def search_transfer_memory_tool(query: dict[str, Any]) -> dict[str, Any]:
    query_text = str(query.get("query") or "")
    path = query.get("path") or "data/memory/cog/transfer_memory.jsonl"
    limit = int(query.get("limit", 5))
    records = search_transfer_memory(query_text, path=path, limit=limit)
    return {"query": query_text, "records": records}


def search_similar_factors_tool(query: dict[str, Any]) -> dict[str, Any]:
    signal = query.get("signal")
    if not isinstance(signal, dict):
        raise ValueError("signal must be a mapping")
    candidate_sources = query.get("candidate_sources")
    if candidate_sources is not None and not isinstance(candidate_sources, list):
        raise ValueError("candidate_sources must be a list when provided")
    return search_similar_alphas(
        signal,
        limit=int(query.get("limit", 8)),
        factor_registry_path=query.get("factor_registry_path") or "data/factor_registry/factors.jsonl",
        candidate_sources=candidate_sources,
    )


def select_mutation_plan_tool(query: dict[str, Any]) -> dict[str, Any]:
    candidates = query.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list")
    feedback_records = query.get("feedback_records")
    if feedback_records is not None and not isinstance(feedback_records, list):
        raise ValueError("feedback_records must be a list when provided")
    memory_context = query.get("memory_context") if isinstance(query.get("memory_context"), dict) else None
    lineage_states = query.get("lineage_states") if isinstance(query.get("lineage_states"), dict) else None
    arm_memory = query.get("arm_memory") if isinstance(query.get("arm_memory"), dict) else None
    plan = select_mutation_plan([item for item in candidates if isinstance(item, dict)], feedback_records, memory_context=memory_context, lineage_states=lineage_states, arm_memory=arm_memory)
    if plan is None:
        return {"plan": None}
    return {
        "plan": {
            "parent_factor_id": str(plan.parent_candidate.get("factor_id") or plan.parent_candidate.get("name") or ""),
            "mutation_focus": plan.mutation_focus,
            "agent_name": plan.agent_name,
            "reason": plan.reason,
            "feedback_count": len(plan.feedback_records),
            "memory_context": plan.memory_context,
        }
    }