from __future__ import annotations

import pytest

from src.llm.three_ai.opinion_analysis import (
    RESEARCH_ANALYSIS_SCHEMA,
    audit_article_opinions,
    generate_article_opinions,
)


def test_generic_analysis_emits_contributions_and_uses_no_specialized_prompt() -> None:
    captured = {}

    def fake_copilot_json(**kwargs):
        captured.update(kwargs)
        return {
            "schema_version": RESEARCH_ANALYSIS_SCHEMA,
            "core_idea": "测试论文贡献",
            "structured_summary": {"problem": "测试问题"},
            "research_contributions": [{
                "contribution_type": "MEASUREMENT_FEATURE",
                "claim": "作者提出新的波动率测量方法。",
                "statement_origin": "AUTHOR_REPORTED",
                "evidence_ids": ["method_data_results"],
                "primary_topic_id": "volatility",
                "factor_research_roles": ["MEASUREMENT_FEATURE", "REGIME_OR_CONDITIONER"],
                "required_observables": ["RETURN_HISTORY"],
                "confidence": "medium",
            }],
            "relation_candidates": [{
                "relation_type": "EXTENDS",
                "review_status": "verified",
                "evidence_ids": ["overview_claims"],
            }],
            "research_ideas": [{
                "research_question": "该测量是否改善父因子的稳定性？",
                "evidence_ids": ["method_data_results"],
                "required_observables": ["RETURN_HISTORY"],
                "confidence": "medium",
            }],
        }

    result = generate_article_opinions(
        {"title": "A paper", "graph_context": {"graph_id": "volatility_graph"}},
        {
            "schema_version": "reading_note_v1",
            "central_claim": "作者提出新的波动率测量方法。",
            "research_topic_category": "volatility",
            "key_results": ["method_data_results: 测量误差下降"],
        },
        {},
        copilot_json=fake_copilot_json,
        model="test-model",
        copilot_bin="unused",
        timeout_sec=1,
    )

    assert result["schema_version"] == RESEARCH_ANALYSIS_SCHEMA
    assert result["specialized_prompt_used"] is False
    assert result["selected_opinion_agent"] == "generic_graph_research"
    assert result["selected_opinion_agent_prompt"] == ""
    assert result["research_contributions"][0]["contribution_type"] == "MEASUREMENT_FEATURE"
    assert result["relation_candidates"][0]["review_status"] == "proposed"
    assert result["research_ideas"][0]["statement_origin"] == "DIGEST_PROPOSED"
    assert result["analysis_validation"]["llm_review_used"] is False
    assert result["analysis_validation"]["status"] == "pass_with_warnings"
    assert captured["payload"]["graph_context"]["graph_id"] == "volatility_graph"
    assert "专门提示词" in captured["prompt"]


def test_retired_llm_audit_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="LLM faithfulness audit is retired"):
        audit_article_opinions()
