#!/usr/bin/env python3
"""Stage-2 generic paper analysis for Paper Graph and Auto-Research.

The active workflow has two LLM roles: evidence-grounded reading and generic
research interpretation.  Publishing is guarded by deterministic validation;
there is deliberately no third LLM faithfulness-review stage.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Mapping


RESEARCH_ANALYSIS_SCHEMA = "graph_research_analysis_v1"
# Kept as an import-compatible name for older callers.  New records use
# RESEARCH_ANALYSIS_SCHEMA as their actual schema_version.
OPINION_ANALYSIS_SCHEMA = RESEARCH_ANALYSIS_SCHEMA

CONTRIBUTION_TYPES = frozenset({
    "MARKET_MECHANISM",
    "EMPIRICAL_EFFECT",
    "MEASUREMENT_FEATURE",
    "ML_REPRESENTATION",
    "PREDICTION_MODEL",
    "LABEL_OR_TARGET",
    "EXECUTION_OR_CONTROL",
    "EVALUATION_METHOD",
    "DATA_OR_MARKET_DESIGN",
    "NEGATIVE_OR_BOUNDARY",
})

FACTOR_RESEARCH_ROLES = frozenset({
    "DIRECT_ALPHA",
    "MECHANISM_PROXY",
    "MEASUREMENT_FEATURE",
    "REGIME_OR_CONDITIONER",
    "LABEL_OR_ESTIMAND",
    "COST_RISK_CONSTRAINT",
    "MODEL_OR_REPRESENTATION",
    "PORTFOLIO_OR_POLICY",
})

STATEMENT_ORIGINS = frozenset({
    "AUTHOR_REPORTED",
    "DIGEST_NORMALIZED",
    "DIGEST_DERIVED",
    "DIGEST_PROPOSED",
    "NOT_DISCLOSED",
})

CONFIDENCE_LEVELS = frozenset({"high", "medium", "low", "undisclosed"})


def _text(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _items(value: Any, limit: int = 8, text_limit: int = 500) -> List[Any]:
    values = value if isinstance(value, list) else ([value] if value else [])
    result: List[Any] = []
    for item in values[:limit]:
        if isinstance(item, dict):
            result.append({
                str(key): (
                    _text(raw, text_limit)
                    if not isinstance(raw, (dict, list))
                    else raw
                )
                for key, raw in list(item.items())[:14]
            })
        else:
            result.append(_text(item, text_limit))
    return result


def _strings(value: Any, limit: int = 16, text_limit: int = 300) -> List[str]:
    values = value if isinstance(value, list) else ([value] if value else [])
    result: List[str] = []
    for item in values[:limit]:
        text = _text(item, text_limit)
        if text and text not in result:
            result.append(text)
    return result


def _confidence(value: Any) -> str:
    confidence = str(value or "undisclosed").strip().lower()
    return confidence if confidence in CONFIDENCE_LEVELS else "undisclosed"


def compact_experiment_evidence_pack(reading_note: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep bounded experiment evidence without converting it into conclusions."""
    setup = reading_note.get("datasets_and_sample_split") or reading_note.get("data_and_empirical_setup")
    if isinstance(setup, dict):
        setup_value: Any = {
            str(key): _text(value, 600) for key, value in list(setup.items())[:10]
        }
    else:
        setup_value = _items(setup, 10, 600)
    return {
        "datasets_and_sample_split": setup_value,
        "experimental_setup": _items(reading_note.get("experimental_setup"), 8, 700),
        "baselines": _items(reading_note.get("baselines"), 10, 500),
        "metrics": _items(reading_note.get("metrics"), 10, 500),
        "empirical_results": _items(reading_note.get("empirical_results"), 10, 700),
        "experimental_formulas": _items(reading_note.get("experimental_formulas"), 6, 600),
        "code_or_algorithm_logic": _items(reading_note.get("code_or_algorithm_logic"), 6, 600),
        "limitations": _items(reading_note.get("limitations"), 8, 500),
        "not_disclosed": _items(reading_note.get("not_disclosed"), 12, 350),
    }


def compact_reading_note(reading_note: Mapping[str, Any]) -> Dict[str, Any]:
    """Build the generic Stage-2 input while retaining evidence references."""
    return {
        "schema_version": reading_note.get("schema_version"),
        "central_claim": _text(reading_note.get("central_claim"), 1000),
        "problem": _text(reading_note.get("problem"), 1000),
        "method_logic": _text(reading_note.get("method_logic"), 1400),
        "core_formulas": _items(reading_note.get("core_formulas"), 10, 700),
        "mechanism_chain": _items(reading_note.get("mechanism_chain"), 10, 600),
        "conclusion_claims": _items(reading_note.get("conclusion_claims"), 8, 600),
        "key_results": _items(reading_note.get("key_results"), 10, 600),
        "faithfulness_constraints_for_next_llm": _items(
            reading_note.get("faithfulness_constraints_for_next_llm"), 12, 400
        ),
        "research_topic_category": _text(reading_note.get("research_topic_category"), 120),
        "legacy_hf_mechanism_category": _text(reading_note.get("hf_mechanism_category"), 120),
        "experiment_evidence_pack": compact_experiment_evidence_pack(reading_note),
        "source_chunk_count": reading_note.get("source_chunk_count"),
    }


def compact_graph_context(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Accept optional graph context without requiring a graph-specific prompt."""
    raw = row.get("graph_context")
    graph_context = dict(raw) if isinstance(raw, dict) else {}
    for key in (
        "graph_id",
        "graph_version",
        "graph_snapshot_id",
        "seed_role",
        "research_question",
        "topic_ids",
        "candidate_categories",
        "neighbor_paper_ids",
        "relation_context",
    ):
        if key not in graph_context and row.get(key) is not None:
            graph_context[key] = row.get(key)
    return {
        str(key): _items(value, 12, 500) if isinstance(value, list) else value
        for key, value in graph_context.items()
    }


def _call(
    copilot_json: Callable[..., Dict[str, Any]],
    prompt: str,
    payload: Dict[str, Any],
    **kwargs: Any,
) -> Dict[str, Any]:
    return copilot_json(prompt=prompt, payload=payload, **kwargs)


def _normalize_contributions(value: Any) -> List[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(rows[:12], start=1):
        if not isinstance(item, dict):
            continue
        evidence_ids = _strings(item.get("evidence_ids") or item.get("evidence_refs"), 16, 240)
        normalized.append({
            "contribution_id": str(item.get("contribution_id") or f"contribution_{index}"),
            "contribution_type": str(item.get("contribution_type") or "").strip().upper(),
            "claim": _text(item.get("claim"), 1200),
            "statement_origin": str(item.get("statement_origin") or "DIGEST_NORMALIZED").strip().upper(),
            "evidence_ids": evidence_ids,
            "evidence_reference_kind": (
                "stable_id" if evidence_ids and all(value.startswith(("ev:", "evidence:")) for value in evidence_ids)
                else "legacy_anchor"
            ),
            "primary_topic_id": _text(item.get("primary_topic_id"), 160),
            "secondary_topic_ids": _strings(item.get("secondary_topic_ids"), 12, 160),
            "factor_research_roles": [
                value.upper() for value in _strings(item.get("factor_research_roles"), 8, 100)
            ],
            "mechanism": _text(item.get("mechanism"), 1200),
            "method_or_estimator": _text(item.get("method_or_estimator"), 1000),
            "market": _text(item.get("market"), 240),
            "asset": _text(item.get("asset"), 240),
            "frequency": _text(item.get("frequency"), 160),
            "horizon": _text(item.get("horizon"), 160),
            "original_inputs": _strings(item.get("original_inputs"), 16, 240),
            "canonical_inputs": _strings(item.get("canonical_inputs"), 16, 160),
            "outputs": _strings(item.get("outputs"), 12, 240),
            "required_observables": [
                value.upper() for value in _strings(item.get("required_observables"), 16, 120)
            ],
            "label_or_estimand": _text(item.get("label_or_estimand"), 600),
            "reported_validation": _text(item.get("reported_validation"), 1200),
            "limitations": _strings(item.get("limitations"), 12, 500),
            "not_disclosed": _strings(item.get("not_disclosed"), 12, 400),
            "confidence": _confidence(item.get("confidence")),
            "route_recommendations": _strings(item.get("route_recommendations"), 8, 240),
        })
    return normalized


def _normalize_relations(value: Any) -> List[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(rows[:16], start=1):
        if not isinstance(item, dict):
            continue
        normalized.append({
            "relation_candidate_id": str(item.get("relation_candidate_id") or f"relation_candidate_{index}"),
            "source_claim_or_contribution_id": _text(item.get("source_claim_or_contribution_id"), 240),
            "target_paper_id": _text(item.get("target_paper_id"), 240),
            "target_description": _text(item.get("target_description"), 800),
            "relation_type": str(item.get("relation_type") or "").strip().upper(),
            "citation_intent": str(item.get("citation_intent") or "UNCLEAR").strip().upper(),
            "evidence_ids": _strings(item.get("evidence_ids") or item.get("evidence_refs"), 12, 240),
            "scope_alignment": _text(item.get("scope_alignment"), 500),
            "confidence": _confidence(item.get("confidence")),
            "review_status": "proposed",
        })
    return normalized


def _normalize_ideas(value: Any, fallback_topic: str) -> List[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(rows[:6], start=1):
        if not isinstance(item, dict):
            continue
        normalized.append({
            "idea_id": str(item.get("idea_id") or item.get("opinion_id") or f"idea_{index}"),
            "statement_origin": "DIGEST_PROPOSED",
            "research_question": _text(item.get("research_question") or item.get("claim"), 1000),
            "rationale": _text(item.get("rationale") or item.get("assessment"), 1200),
            "source_contribution_ids": _strings(item.get("source_contribution_ids"), 8, 240),
            "evidence_ids": _strings(item.get("evidence_ids") or item.get("evidence_refs"), 12, 240),
            "required_observables": [
                value.upper() for value in _strings(item.get("required_observables"), 16, 120)
            ],
            "suggested_test": _text(item.get("suggested_test"), 1000),
            "expected_failure_modes": _strings(item.get("expected_failure_modes"), 10, 400),
            "limitations": _strings(item.get("limitations"), 10, 400),
            "confidence": _confidence(item.get("confidence")),
            "topic_id": _text(item.get("topic_id") or fallback_topic, 160),
        })
    return normalized


def _compatibility_opinions(ideas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the current dashboard usable without making it authoritative."""
    return [{
        "opinion_id": idea["idea_id"],
        "type": "idea",
        "idea_category": idea["topic_id"] or "general",
        "claim": idea["research_question"],
        "assessment": idea["rationale"],
        "supporting_evidence": json.dumps(idea["evidence_ids"], ensure_ascii=False),
        "evidence_anchor": ", ".join(idea["evidence_ids"]),
        "confidence": idea["confidence"],
        "limitations": "; ".join(idea["limitations"]),
        "dataset_details": "; ".join(idea["required_observables"]),
        "metric_explanation": idea["suggested_test"],
        "statement_origin": "DIGEST_PROPOSED",
    } for idea in ideas]


def validate_research_analysis(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Run deterministic schema and semantic-boundary checks; no LLM is called."""
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    if value.get("schema_version") != RESEARCH_ANALYSIS_SCHEMA:
        errors.append({"code": "SCHEMA_VERSION_MISMATCH", "path": "schema_version"})
    contributions = value.get("research_contributions")
    if not isinstance(contributions, list):
        errors.append({"code": "CONTRIBUTIONS_NOT_LIST", "path": "research_contributions"})
        contributions = []
    for index, contribution in enumerate(contributions):
        path = f"research_contributions[{index}]"
        if not isinstance(contribution, dict):
            errors.append({"code": "CONTRIBUTION_NOT_OBJECT", "path": path})
            continue
        if contribution.get("contribution_type") not in CONTRIBUTION_TYPES:
            errors.append({"code": "UNKNOWN_CONTRIBUTION_TYPE", "path": path + ".contribution_type"})
        if contribution.get("statement_origin") not in STATEMENT_ORIGINS:
            errors.append({"code": "UNKNOWN_STATEMENT_ORIGIN", "path": path + ".statement_origin"})
        if not contribution.get("claim"):
            errors.append({"code": "EMPTY_CONTRIBUTION_CLAIM", "path": path + ".claim"})
        if not contribution.get("evidence_ids"):
            warnings.append({"code": "MISSING_CONTRIBUTION_EVIDENCE", "path": path + ".evidence_ids"})
        for role in contribution.get("factor_research_roles") or []:
            if role not in FACTOR_RESEARCH_ROLES:
                errors.append({"code": "UNKNOWN_FACTOR_RESEARCH_ROLE", "path": path + ".factor_research_roles"})
        if contribution.get("evidence_reference_kind") == "legacy_anchor":
            warnings.append({"code": "LEGACY_EVIDENCE_ANCHOR", "path": path + ".evidence_ids"})
    for index, relation in enumerate(value.get("relation_candidates") or []):
        path = f"relation_candidates[{index}]"
        if not isinstance(relation, dict) or relation.get("review_status") != "proposed":
            errors.append({"code": "RELATION_MUST_REMAIN_PROPOSED", "path": path})
    for index, idea in enumerate(value.get("research_ideas") or []):
        if not isinstance(idea, dict) or idea.get("statement_origin") != "DIGEST_PROPOSED":
            errors.append({"code": "IDEA_MUST_BE_PROPOSED", "path": f"research_ideas[{index}]"})
    return {
        "schema_version": "research_analysis_validation_v1",
        "validator": "deterministic",
        "llm_review_used": False,
        "status": "reject" if errors else "pass_with_warnings" if warnings else "pass",
        "errors": errors,
        "warnings": warnings,
        "publishable": not errors,
    }


def generate_article_opinions(
    row: Dict[str, Any],
    reading_note: Dict[str, Any],
    evidence_pack: Dict[str, Any],
    *,
    copilot_json: Callable[..., Dict[str, Any]],
    model: str,
    copilot_bin: str,
    timeout_sec: int,
    api_key_env: str = "",
) -> Dict[str, Any]:
    """Generate one generic Graph/Auto-Research analysis for any paper."""
    topic = str(reading_note.get("research_topic_category") or "other")
    graph_context = compact_graph_context(row)
    prompt = (
        "你是 Paper Digest 的通用论文研究分析模型。只基于 reading_note_v1、压缩实验证据和可选 graph_context 工作；"
        "本版本不使用按 graph 或高频类别定制的专门提示词，也不强迫论文落入单一高频 idea 类别。"
        "你的核心任务是把一篇论文拆成多个相互独立、可由证据复查的 research_contributions，并给出服务 Paper Graph 与 Auto-Research 的语义接口。"
        "每个 contribution 必须且只能选择一个 contribution_type：MARKET_MECHANISM、EMPIRICAL_EFFECT、MEASUREMENT_FEATURE、"
        "ML_REPRESENTATION、PREDICTION_MODEL、LABEL_OR_TARGET、EXECUTION_OR_CONTROL、EVALUATION_METHOD、"
        "DATA_OR_MARKET_DESIGN、NEGATIVE_OR_BOUNDARY。"
        "factor_research_roles 可多选：DIRECT_ALPHA、MECHANISM_PROXY、MEASUREMENT_FEATURE、REGIME_OR_CONDITIONER、"
        "LABEL_OR_ESTIMAND、COST_RISK_CONSTRAINT、MODEL_OR_REPRESENTATION、PORTFOLIO_OR_POLICY。"
        "必须区分语义来源：论文明确报告用 AUTHOR_REPORTED；忠实规范化用 DIGEST_NORMALIZED；"
        "由证据保守推导用 DIGEST_DERIVED；未来研究想法只能用 DIGEST_PROPOSED；未披露用 NOT_DISCLOSED。"
        "论文事实、Digest 推导和研究建议不得写进同一个事实字段。"
        "evidence_ids 优先引用输入已有的稳定 evidence_id；当前输入只有 chunk_id/evidence_ref 时可暂时引用该 anchor，但不得伪造 evidence ID。"
        "required_observables 只写论文语义数据需求，例如 RETURN_HISTORY、PRICE_LEVEL_OHLC、VOLUME_TURNOVER、"
        "L2_BOOK_SNAPSHOT、ORDER_EVENT_STREAM、TRADE_PRINTS_SIGN、FUNDAMENTAL_PIT、MARKET_CAP_SHARES、"
        "INDUSTRY_CLASSIFICATION、DERIVATIVES_CHAIN、CROSS_MARKET_DATA、TEXT_EVENT、MACRO_ALTERNATIVE、"
        "EXECUTION_FILL_COST、TRAINED_MODEL_ARTIFACT、SIMULATOR；不得写本地列名、文件路径或假定代理可用。"
        "route_recommendations 只是语义建议，不能宣布 Agent Alpha 已具备数据、因子有效、IC 显著或可部署。"
        "只有存在直接 citation context 或 graph_context 证据时才输出 relation_candidates；所有关系必须保持 proposed，"
        "不得直接声称 SUPPORTS、CONTRADICTS 或 REPLICATES 已核验。"
        "research_ideas 最多三条，必须从 contribution 出发，标记 DIGEST_PROPOSED，并写清数据需求、建议检验和失败方式。"
        "不得补造样本、公式、模型细节、统计量、IC、Sharpe、回测、交易成本、样本外表现或容量。"
        "除 JSON key、枚举、ID、公式、变量名和证据原文外，所有自然语言字段使用简体中文。"
        f"输出 schema_version='{RESEARCH_ANALYSIS_SCHEMA}'，不要 Markdown，只输出严格 JSON。"
    )
    payload = {
        "article_meta": {
            "title": row.get("title"),
            "url": row.get("url"),
            "source_id": row.get("source_id"),
            "arxiv_id": row.get("arxiv_id"),
            "tags": row.get("tags", []),
        },
        "reading_note": compact_reading_note(reading_note),
        "experiment_evidence_pack": compact_experiment_evidence_pack(reading_note),
        "graph_context": graph_context,
        "required_schema": {
            "schema_version": RESEARCH_ANALYSIS_SCHEMA,
            "analysis_mode": "generic_graph_paper",
            "core_idea": "论文核心贡献的简洁说明",
            "structured_summary": {
                "problem": "",
                "method": "",
                "author_claim": "",
                "evidence_status": "",
                "limitations": "",
                "critical_assessment": "",
                "missing_tests": "",
                "datasets": "",
                "baseline_models": "",
                "metrics_explained": "",
                "experiment_details": "",
                "plain_language_takeaway": "",
            },
            "research_contributions": [{
                "contribution_id": "contribution_1",
                "contribution_type": "one allowed contribution type",
                "claim": "",
                "statement_origin": "AUTHOR_REPORTED/DIGEST_NORMALIZED/DIGEST_DERIVED/NOT_DISCLOSED",
                "evidence_ids": [],
                "primary_topic_id": topic,
                "secondary_topic_ids": [],
                "factor_research_roles": [],
                "mechanism": "",
                "method_or_estimator": "",
                "market": "",
                "asset": "",
                "frequency": "",
                "horizon": "",
                "original_inputs": [],
                "canonical_inputs": [],
                "outputs": [],
                "required_observables": [],
                "label_or_estimand": "",
                "reported_validation": "",
                "limitations": [],
                "not_disclosed": [],
                "confidence": "high/medium/low/undisclosed",
                "route_recommendations": [],
            }],
            "relation_candidates": [],
            "research_ideas": [{
                "idea_id": "idea_1",
                "statement_origin": "DIGEST_PROPOSED",
                "research_question": "",
                "rationale": "",
                "source_contribution_ids": [],
                "evidence_ids": [],
                "required_observables": [],
                "suggested_test": "",
                "expected_failure_modes": [],
                "limitations": [],
                "confidence": "high/medium/low/undisclosed",
                "topic_id": topic,
            }],
            "graph_research_summary": {
                "paper_roles": [],
                "graph_value_reasons": [],
                "evidence_gaps": [],
                "data_requirement_summary": [],
            },
        },
    }
    parsed = _call(
        copilot_json,
        prompt,
        payload,
        model=model,
        copilot_bin=copilot_bin,
        timeout_sec=timeout_sec,
        api_key_env=api_key_env,
    )
    contributions = _normalize_contributions(parsed.get("research_contributions"))
    relations = _normalize_relations(parsed.get("relation_candidates"))
    ideas = _normalize_ideas(parsed.get("research_ideas") or parsed.get("article_opinions"), topic)
    result = {
        "schema_version": RESEARCH_ANALYSIS_SCHEMA,
        "analysis_mode": "generic_graph_paper",
        "specialized_prompt_used": False,
        "core_idea": _text(parsed.get("core_idea"), 700),
        "structured_summary": parsed.get("structured_summary") if isinstance(parsed.get("structured_summary"), dict) else {},
        "research_contributions": contributions,
        "relation_candidates": relations,
        "research_ideas": ideas,
        "graph_research_summary": parsed.get("graph_research_summary") if isinstance(parsed.get("graph_research_summary"), dict) else {},
        "graph_context": graph_context,
        "analysis_agent": f"paper-generic-graph-research-agent:{model}:{RESEARCH_ANALYSIS_SCHEMA}",
        # Compatibility-only view for the current renderer and archives.
        "article_opinions": _compatibility_opinions(ideas),
        "opinion_category": "general",
        "selected_opinion_agent": "generic_graph_research",
        "selected_opinion_agent_prompt": "",
        "plain_language_takeaway": _text(parsed.get("plain_language_takeaway"), 1200),
        "score_dimensions": parsed.get("score_dimensions") if isinstance(parsed.get("score_dimensions"), dict) else {},
        "recommendation_score": parsed.get("recommendation_score"),
    }
    result["analysis_validation"] = validate_research_analysis(result)
    return result


def audit_article_opinions(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
    """Retired API guard: the active workflow intentionally has no LLM audit."""
    raise RuntimeError(
        "LLM faithfulness audit is retired; use validate_research_analysis() "
        "for deterministic publication checks"
    )


__all__ = [
    "CONTRIBUTION_TYPES",
    "FACTOR_RESEARCH_ROLES",
    "OPINION_ANALYSIS_SCHEMA",
    "RESEARCH_ANALYSIS_SCHEMA",
    "audit_article_opinions",
    "compact_experiment_evidence_pack",
    "compact_reading_note",
    "generate_article_opinions",
    "validate_research_analysis",
]
