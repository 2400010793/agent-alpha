from __future__ import annotations

from agent_alpha.search.iterative_enhancer import enhance_candidates


def _candidate(factor_id: str, prefix_expression: object, fields: list[str], windows: list[int] | None = None) -> dict:
    return {
        "factor_id": factor_id,
        "name": factor_id,
        "prefix_expression": prefix_expression,
        "expression": "",
        "fields": fields,
        "windows": windows or [],
        "direction": "positive",
        "source_signal_id": f"sig_{factor_id}",
        "source_reading_note_id": f"note_{factor_id}",
        "mechanism_tags": ["order_book_pressure"],
    }


def test_enhancer_without_llm_client_does_not_make_cosmetic_rule_mutations() -> None:
    candidates = [
        _candidate("lob_imbalance_l1", ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]], ["bidV1", "askV1"]),
        _candidate("spread_pressure", ["zscore", "spread_l1", 60], ["spread_l1"], [60]),
    ]
    feedback = [
        {"factor_id": "lob_imbalance_l1", "tags": ["weak_rankic"]},
        {"factor_id": "spread_pressure", "status": "good"},
    ]

    assert enhance_candidates(candidates, feedback, max_new_candidates=10) == []