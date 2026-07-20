from __future__ import annotations

import pytest

from agent_alpha.signals.signal_schema import AlphaSignal, validate_alpha_signal


def test_alpha_signal_schema_validate_passes() -> None:
    signal = AlphaSignal(
        signal_id="sig_lob_imbalance",
        source_paper_id="paper_demo",
        source_reading_note_id="note_demo",
        signal_name="LOB imbalance pressure",
        market_intuition="Visible bid depth exceeding ask depth may proxy buying pressure.",
        hypothesis="Top-book imbalance can forecast short-horizon continuation.",
        expected_direction="positive",
        hf_mechanism_tags=["order_book_pressure"],
        candidate_fields=["bidV1", "askV1"],
        evidence_ids=["ev_0001"],
    ).to_dict()

    validate_alpha_signal(signal)
    assert signal["schema_version"] == "alpha_signal_v1"
    assert signal["created_at"]


def test_alpha_signal_schema_rejects_missing_and_bad_direction() -> None:
    signal = AlphaSignal(
        signal_id="sig_lob_imbalance",
        source_paper_id="paper_demo",
        source_reading_note_id="note_demo",
        signal_name="LOB imbalance pressure",
        market_intuition="intuition",
        hypothesis="hypothesis",
        expected_direction="positive",
        hf_mechanism_tags=[],
        candidate_fields=[],
        evidence_ids=[],
    ).to_dict()
    signal.pop("hypothesis")
    with pytest.raises(ValueError, match="missing"):
        validate_alpha_signal(signal)

    signal = AlphaSignal.from_mapping({**signal, "hypothesis": "hypothesis", "expected_direction": "sideways"}).to_dict()
    with pytest.raises(ValueError, match="expected_direction"):
        validate_alpha_signal(signal)