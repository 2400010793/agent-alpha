from paper_graph.gate2_audit import (
    build_gate2_summary,
    build_stratified_review_sample,
    evaluate_review_labels,
    reaudit_row,
)
from paper_graph.openalex_snapshot import classify_quant_work


def _row(openalex_id: str, title: str, status: str = "accepted") -> dict:
    work = {
        "openalex_id": openalex_id,
        "canonical_paper_id": f"openalex:{openalex_id}",
        "title": title,
        "publication_year": 2024,
    }
    return {
        **work,
        "finance_status": status,
        "quant_match": classify_quant_work(work),
        "graph_seed_eligible": False,
        "digest_seed_eligible": False,
    }


def test_summary_preserves_retrieval_count_and_records_transitions() -> None:
    rows = [
        reaudit_row(_row("W1", "Order Flow in Limit Order Books")),
        reaudit_row(_row("W2", "Machine Learning for Weather Forecasting")),
    ]
    summary = build_gate2_summary(rows)
    assert summary["retrieval_count"] == 2
    assert summary["unique_openalex_id_count"] == 2
    assert summary["status_transitions"]["accepted->accepted"] == 1
    assert summary["status_transitions"]["accepted->rejected"] == 1


def test_review_sample_is_deterministic_and_keeps_human_labels_empty() -> None:
    rows = [
        reaudit_row(_row("W1", "Order Flow in Limit Order Books")),
        reaudit_row(_row("W2", "Machine Learning for Weather Forecasting")),
        reaudit_row(_row("W3", "Intraday Traffic Flow")),
        reaudit_row(_row("W4", "Market Liquidity and Volatility")),
    ]
    first = build_stratified_review_sample(rows, sample_size=4, random_seed=7)
    second = build_stratified_review_sample(rows, sample_size=4, random_seed=7)
    assert first == second
    assert {row["openalex_id"] for row in first} == {"W1", "W2", "W3", "W4"}
    assert all(row["human_finance_status"] is None for row in first)
    assert any("focus:machine learning" in row["review_strata"] for row in first)


def test_duplicate_openalex_id_is_rejected() -> None:
    row = reaudit_row(_row("W1", "Order Flow in Limit Order Books"))
    try:
        build_gate2_summary([row, row])
    except ValueError as exc:
        assert "duplicate OpenAlex ID" in str(exc)
    else:
        raise AssertionError("duplicate OpenAlex ID should fail")


def test_label_evaluation_requires_completion_and_precision_threshold() -> None:
    pending = [
        {"openalex_id": "W1", "automatic_finance_status": "accepted", "human_finance_status": None},
        {"openalex_id": "W2", "automatic_finance_status": "accepted", "human_finance_status": "accepted"},
    ]
    assert evaluate_review_labels(pending)["finance_review_status"] == "pending_manual_review"

    complete = [
        {"openalex_id": f"W{index}", "automatic_finance_status": "accepted", "human_finance_status": "accepted" if index < 9 else "review"}
        for index in range(10)
    ]
    result = evaluate_review_labels(complete, accepted_precision_threshold=0.90)
    assert result["accepted_precision"] == 0.9
    assert result["finance_review_status"] == "passed"