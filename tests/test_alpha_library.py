from __future__ import annotations

from pathlib import Path

import pytest

from agent_alpha.library.alpha_library import append_alpha_record, load_alpha_records, search_elite


def test_alpha_library_admits_record_using_daily_rankic_threshold(tmp_path: Path) -> None:
    path = tmp_path / "alpha_library.jsonl"

    record = append_alpha_record(
        {
            "factor_id": "lob_imbalance_l1",
            "name": "lob_imbalance_l1",
            "decision": "accept",
            "metrics": {"daily_rankic": 0.2, "finite_ratio": 0.95},
            "mechanism_tags": ["order_book_pressure"],
            "summary": "Elite top-book pressure alpha.",
        },
        path=path,
    )

    assert record["status"] == "admitted"
    assert load_alpha_records(path)[0]["factor_id"] == "lob_imbalance_l1"
    assert search_elite("top-book", path=path)[0]["factor_id"] == "lob_imbalance_l1"


def test_alpha_library_rejects_records_below_admission_threshold(tmp_path: Path) -> None:
    path = tmp_path / "alpha_library.jsonl"

    with pytest.raises(ValueError, match="rankic"):
        append_alpha_record(
            {"factor_id": "weak", "decision": "accept", "metrics": {"daily_rankic": 0.001, "finite_ratio": 0.95}},
            path=path,
        )

    with pytest.raises(ValueError, match="finite_ratio"):
        append_alpha_record(
            {"factor_id": "sparse", "decision": "accept", "metrics": {"daily_rankic": 0.2, "finite_ratio": 0.1}},
            path=path,
        )