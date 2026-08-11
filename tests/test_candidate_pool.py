from __future__ import annotations

from pathlib import Path

from agent_alpha.search.candidate_pool import CandidatePool, build_pool_record, deduplicate_candidates


def _candidate(
    factor_id: str,
    expression: str,
    *,
    prefix_expression=None,
    source_signal_id: str = "sig_demo",
) -> dict:
    return {
        "factor_id": factor_id,
        "name": factor_id,
        "expression": expression,
        "prefix_expression": prefix_expression,
        "fields": ["bidV1", "askV1"],
        "source_signal_id": source_signal_id,
        "source_reading_note_id": "note_demo",
        "mechanism_tags": ["order_book_pressure"],
    }


def test_deduplicate_candidates_removes_same_prefix_expression() -> None:
    prefix = ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]]
    candidates = [
        _candidate("lob_imbalance_a", "safe_div(bidV1 - askV1, bidV1 + askV1)", prefix_expression=prefix),
        _candidate("lob_imbalance_b", "different_text_is_ignored_when_prefix_matches", prefix_expression=prefix),
    ]

    deduplicated = deduplicate_candidates(candidates)

    assert deduplicated == [candidates[0]]


def test_deduplicate_candidates_keeps_different_expressions() -> None:
    candidates = [
        _candidate("spread", "bidV1 - askV1"),
        _candidate("depth", "bidV1 + askV1"),
    ]

    deduplicated = deduplicate_candidates(candidates)

    assert deduplicated == candidates


def test_build_pool_record_preserves_lineage_generation_and_status() -> None:
    record = build_pool_record(
        _candidate("lob_imbalance", "safe_div(bidV1 - askV1, bidV1 + askV1)"),
        parent_ids=["cand_parent_a", "cand_parent_b"],
        generation=2,
        status="validated",
    )

    assert record.parent_ids == ["cand_parent_a", "cand_parent_b"]
    assert record.generation == 2
    assert record.status == "validated"
    assert record.source_signal_id == "sig_demo"
    assert record.source_reading_note_id == "note_demo"
    assert record.mechanism_tags == ["order_book_pressure"]


def test_candidate_identity_is_scoped_to_research_context() -> None:
    candidate = _candidate("spread", "bidV1 - askV1")
    first = build_pool_record({**candidate, "research_run_id": "run_a"})
    second = build_pool_record({**candidate, "research_run_id": "run_b"})

    assert first.candidate_id != second.candidate_id
    assert first.research_run_id == "run_a"


def test_candidate_pool_add_avoids_duplicate_expression() -> None:
    pool = CandidatePool()
    first = pool.add(_candidate("spread_a", "bidV1 - askV1"))
    second = pool.add(_candidate("spread_b", "bidV1 - askV1"))

    assert second == first
    assert pool.by_generation(0) == [first]


def test_candidate_pool_update_status_changes_status() -> None:
    pool = CandidatePool()
    record = pool.add(_candidate("spread", "bidV1 - askV1"))

    updated = pool.update_status(record.candidate_id, "accepted")

    assert updated.status == "accepted"
    assert updated.created_at == record.created_at
    assert updated.updated_at >= record.updated_at
    assert pool.by_status("accepted") == [updated]
    assert pool.by_status("created") == []


def test_candidate_pool_jsonl_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "candidate_pool.jsonl"
    pool = CandidatePool()
    first = pool.add(_candidate("spread", "bidV1 - askV1"), status="validated")
    second = pool.add(_candidate("depth", "bidV1 + askV1"), parent_ids=[first.candidate_id], generation=1)

    pool.to_jsonl(path)
    restored = CandidatePool.from_jsonl(path)

    assert restored.by_status("validated") == [first]
    assert restored.by_generation(1) == [second]
