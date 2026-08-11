from __future__ import annotations

import json
from pathlib import Path

from agent_alpha.rag.alpha_memory_retriever import search_similar_alphas
from agent_alpha.rag.field_retriever import recommend_fields_for_signal


def _signal() -> dict:
    return {
        "signal_id": "depth_hidden_liquidity",
        "signal_name": "Depth and hidden liquidity pressure",
        "market_intuition": "Hidden depute flow and depth imbalance create short-term pressure.",
        "hypothesis": "Depth imbalance with depute flow should forecast short-horizon returns.",
        "hf_mechanism_tags": ["order_book_pressure", "hidden_liquidity"],
        "candidate_fields": ["depth_imbalance_l1", "totalDeputeBuy", "totalDeputeSell", "ret60s"],
    }


def test_recommend_fields_filters_labels_and_prioritizes_runtime_safe_fields() -> None:
    result = recommend_fields_for_signal(_signal(), limit=8)

    names = result["recommended_field_names"]
    assert "ret60s" not in names
    assert "depth_imbalance_l1" in names
    assert "totalDeputeBuy" in names
    assert "totalDeputeSell" in names
    assert "depth_imbalance_l1" in result["runtime_safe_derived_fields"]


def test_search_similar_alphas_uses_candidate_source_overlap(tmp_path: Path) -> None:
    source = tmp_path / "candidates.json"
    source.write_text(
        json.dumps(
            {
                "factor_candidates": [
                    {
                        "factor_id": "depth_depute_confirm",
                        "fields": ["depth_imbalance_l1", "totalDeputeBuy", "totalDeputeSell"],
                        "mechanism_tags": ["order_book_pressure", "hidden_liquidity"],
                        "prefix_expression": ["zscore", "depth_imbalance_l1", 60],
                        "metrics": {"daily_rankic_mean": 0.12},
                    },
                    {
                        "factor_id": "unrelated_volume",
                        "fields": ["volume"],
                        "mechanism_tags": ["trade_impact"],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = search_similar_alphas(_signal(), candidate_sources=[source], limit=3)

    assert result["similar_factors"][0]["factor_id"] == "depth_depute_confirm"
    assert any(reason.startswith("tag_overlap") for reason in result["similar_factors"][0]["reasons"])