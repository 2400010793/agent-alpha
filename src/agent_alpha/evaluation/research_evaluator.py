from __future__ import annotations

import uuid

from agent_alpha.config import load_yaml
from agent_alpha.evaluation.economic_logic_checker import check_economic_logic
from agent_alpha.evaluation.implementation_checker import check_implementation
from agent_alpha.evaluation.risk_analyzer import analyze_risk
from agent_alpha.evaluation.statistical_tester import test_statistical_strength
from agent_alpha.evaluation.evaluation_schema import EvaluationRecord


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def evaluate_research_quality(
    candidate: dict,
    metrics: dict | None = None,
    compile_result: dict | None = None,
    render_result: dict | None = None,
    source_signal: dict | None = None,
    config_path: str = "configs/quality_evaluation.yaml",
) -> dict:
    """Make a simple accept/revise/reject decision for a candidate factor."""
    config = load_yaml(config_path)
    metrics = dict(metrics or {})
    impl = check_implementation(candidate, compile_result=compile_result, render_result=render_result)
    stats = test_statistical_strength(metrics, config, expected_direction=str(candidate.get("direction") or candidate.get("expected_direction") or "unknown"))
    risk = analyze_risk(metrics, config)
    econ = check_economic_logic(candidate, source_signal=source_signal)

    failure_modes = _dedupe(list(impl["failure_modes"]) + list(stats["reasons"]) + list(risk["risk_flags"]))
    required_revisions: list[str] = []
    if not impl["ok"]:
        required_revisions.append(f"Fix implementation gate: {impl['message']}")
    if not stats["ok"]:
        required_revisions.extend(f"Improve statistical strength: {reason}" for reason in stats["reasons"])
    if not risk["ok"]:
        required_revisions.extend(f"Reduce evaluation risk: {flag}" for flag in risk["risk_flags"])
    if not econ["ok"]:
        required_revisions.append(f"Clarify economic logic: {econ['reason']}")

    if not impl["ok"]:
        decision = "reject"
    elif stats["ok"] and risk["ok"] and econ["ok"]:
        decision = "accept"
    else:
        decision = "revise"

    good_patterns: list[str] = []
    bad_patterns: list[str] = []
    if impl["ok"]:
        good_patterns.append("valid_factor_implementation")
    if stats["ok"]:
        good_patterns.append("rankic_passed_threshold")
    if econ["ok"]:
        good_patterns.append("mechanism_direction_rationale_present")
    if failure_modes:
        bad_patterns.extend(failure_modes)

    evaluation = EvaluationRecord(
        evaluation_id=uuid.uuid4().hex,
        factor_id=str(candidate.get("factor_id") or candidate.get("name") or ""),
        factor_name=str(candidate.get("name") or candidate.get("factor_name") or candidate.get("factor_id") or ""),
        decision=decision,
        metrics=metrics,
        statistical_summary=stats["summary"],
        implementation_summary=impl["message"],
        economic_summary=econ["summary"],
        risk_summary=risk["summary"],
        failure_modes=failure_modes,
        good_patterns=good_patterns,
        bad_patterns=bad_patterns,
        required_revisions=required_revisions,
    ).to_dict()
    return {
        "schema_version": "research_review_v1",
        "factor_id": evaluation["factor_id"],
        "factor_name": evaluation["factor_name"],
        "decision": decision,
        "statistical_summary": stats["summary"],
        "risk_summary": risk["summary"],
        "economic_logic_summary": econ["summary"],
        "implementation_quality_summary": impl["message"],
        "failure_modes": failure_modes,
        "required_revisions": required_revisions,
        "good_patterns": good_patterns,
        "bad_patterns": bad_patterns,
        "metrics": metrics,
        "checks": {"implementation": impl, "statistical": stats, "risk": risk, "economic_logic": econ},
        "evaluation_record": evaluation,
    }
