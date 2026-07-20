from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_alpha.factors.expression_validator import validate_factor_candidate


def _flag_failed(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    status = str(payload.get("validation_status") or payload.get("status") or "").casefold()
    return status == "failed" or payload.get("ok") is False


def _factor_file_missing(render_result: dict[str, Any] | None) -> bool:
    if not render_result:
        return False
    factor_file = render_result.get("factor_file") or render_result.get("path") or render_result.get("file_path")
    if not factor_file:
        return True
    return not Path(str(factor_file)).exists()


def check_implementation(candidate: dict, compile_result: dict | None = None, render_result: dict | None = None) -> dict:
    validation = validate_factor_candidate(candidate)
    failure_modes: list[str] = []
    if not validation.ok:
        failure_modes.append("validator_failed")
    schema_text = " ".join(validation.schema_errors).casefold()
    if validation.field_result.label_leakage_fields or "label" in schema_text or "leakage" in schema_text or "blocked" in schema_text:
        failure_modes.append("field_leakage")
    if _flag_failed(compile_result):
        failure_modes.append("compile_failed")
    if _flag_failed(render_result):
        failure_modes.append("render_validation_failed")
    if render_result is not None and _factor_file_missing(render_result):
        failure_modes.append("missing_factor_file")

    messages = []
    if validation.message != "ok":
        messages.append(validation.message)
    if compile_result and compile_result.get("message"):
        messages.append(str(compile_result["message"]))
    if render_result and render_result.get("message"):
        messages.append(str(render_result["message"]))
    message = "; ".join(messages) if messages else "implementation checks passed"
    return {
        "ok": not failure_modes,
        "message": message,
        "failure_modes": failure_modes,
        "used_fields": validation.field_result.used_fields,
    }