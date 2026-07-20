from __future__ import annotations

from typing import Any

from agent_alpha.llm.client import LLMSettings
from agent_alpha.reading.evidence_pack import build_evidence_pack_v2, build_reading_tasks_from_evidence_pack
from agent_alpha.reading.llm_paper_reader import build_llm_reading_note, select_reading_chunks
from agent_alpha.reading.note_schema import validate_reading_note
from agent_alpha.signals.reading_gate import ReadingGateConfig, evaluate_reading_gate


class FakeLLMClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.settings = LLMSettings(base_url="https://example.invalid", api_key="fake-key", model="fake-model")
        self.messages: list[dict[str, str]] | None = None

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.messages = messages
        return self.payload


def _chunks() -> list[dict[str, Any]]:
    return [
        {
            "doc_id": "paper_lob",
            "chunk_id": "paper_lob::chunk_0001",
            "source_type": "paper",
            "source_format": "latex",
            "source_url": "https://arxiv.org/abs/0000.00000",
            "title": "Limit Order Book Pressure",
            "authors": ["A. Researcher"],
            "published_at": "2026-01-01",
            "section": "Mechanism",
            "page": None,
            "text": "The paper studies whether high-frequency order book imbalance predicts intraday returns.",
            "formula_blocks": ["I_t = (bidV1_t - askV1_t) / (bidV1_t + askV1_t)"],
            "table_captions": [],
            "figure_captions": [],
        }
    ]


def test_build_llm_reading_note_with_fake_llm_passes_schema_and_gate() -> None:
    fake_note = {
        "schema_version": "reading_note_v1",
        "paper_id": "paper_lob",
        "paper_title": "Limit Order Book Pressure",
        "source_url": "https://arxiv.org/abs/0000.00000",
        "source_type": "paper",
        "research_question": "Does order book imbalance predict intraday returns? chunk_id=paper_lob::chunk_0001",
        "market_setting": "High-frequency limit order book market. chunk_id=paper_lob::chunk_0001",
        "data_used": "Tick/order book data are discussed, but sample period is 输入未披露.",
        "main_mechanism": "Visible bid and ask depth proxy short-horizon liquidity pressure. chunk_id=paper_lob::chunk_0001",
        "mechanism_chain": ["paper_lob::chunk_0001: bid/ask depth imbalance -> liquidity pressure -> short-horizon return pressure"],
        "core_formulas": ["paper_lob::chunk_0001: I_t = (bidV1_t - askV1_t) / (bidV1_t + askV1_t)"],
        "variable_definitions": ["paper_lob::chunk_0001: bidV1 and askV1 are top-book visible depths"],
        "empirical_findings": ["输入未披露"],
        "limitations": ["sample, costs, and out-of-sample tests are 输入未披露"],
        "possible_trading_intuitions": ["paper_lob::chunk_0001: imbalance may be a high-frequency pressure intuition, not a factor here"],
        "supporting_evidence": [
            {
                "evidence_id": "ev_0001",
                "chunk_id": "paper_lob::chunk_0001",
                "quote": "order book imbalance predicts intraday returns",
                "section": "Mechanism",
                "page": None,
                "why_relevant": "Supports the research question and mechanism.",
            }
        ],
        "not_disclosed": ["sample", "cost", "out_of_sample"],
        "score_dimensions": {
            "relevance": {"score": 8, "comment": "HF LOB topic", "evidence": "paper_lob::chunk_0001", "critique": "single chunk"},
            "mechanism": {"score": 8, "comment": "clear mechanism", "evidence": "paper_lob::chunk_0001", "critique": "needs more evidence"},
            "statistical": {"score": 4, "comment": "empirics undisclosed", "evidence": "输入未披露", "critique": "sample missing"},
            "implementation": {"score": 8, "comment": "fields available", "evidence": "paper_lob::chunk_0001", "critique": "formula only"},
            "cost_sensitivity": {"score": 3, "comment": "costs missing", "evidence": "输入未披露", "critique": "cost missing"},
            "generality": {"score": 6, "comment": "generic LOB", "evidence": "paper_lob::chunk_0001", "critique": "single paper"},
        },
        "recommendation_score": 1,
        "created_at": "2026-07-17T00:00:00+00:00",
        "alpha_signal": "must be dropped by normalize output selection",
        "factor": "must be dropped by normalize output selection",
    }
    client = FakeLLMClient(fake_note)

    note = build_llm_reading_note(_chunks(), client)  # type: ignore[arg-type]

    validate_reading_note(note)
    gate = evaluate_reading_gate(note, ReadingGateConfig(min_recommendation_score=5.5))
    assert gate.should_continue is True
    assert note["recommendation_score"] == 6.17
    assert "alpha_signal" not in note
    assert "factor" not in note
    assert client.messages is not None
    assert "Do not generate alpha signals" in client.messages[0]["content"]
    assert "fake-key" not in str(client.messages)


def test_llm_reader_fills_missing_disclosures_and_score_dimensions() -> None:
    client = FakeLLMClient(
        {
            "research_question": "chunk_id=paper_lob::chunk_0001: question",
            "supporting_evidence": [
                {
                    "chunk_id": "paper_lob::chunk_0001",
                    "quote": "high-frequency order book imbalance",
                    "section": "Mechanism",
                    "page": None,
                    "why_relevant": "question evidence",
                }
            ],
            "mechanism_chain": ["paper_lob::chunk_0001: mechanism"],
            "possible_trading_intuitions": ["paper_lob::chunk_0001: intuition only"],
        }
    )

    note = build_llm_reading_note(_chunks(), client)  # type: ignore[arg-type]

    validate_reading_note(note)
    assert note["schema_version"] == "reading_note_v1"
    assert note["paper_id"] == "paper_lob"
    assert note["data_used"] == "输入未披露"
    assert set(note["score_dimensions"]) == {"relevance", "mechanism", "statistical", "implementation", "cost_sensitivity", "generality"}


def test_select_reading_chunks_prefers_formula_data_and_limit_sections() -> None:
    chunks = [
        {"doc_id": "p", "chunk_id": "c_intro", "section": "Introduction", "text": "central claim and contribution", "formula_blocks": []},
        {"doc_id": "p", "chunk_id": "c_formula", "section": "Model", "text": "where variables are defined", "formula_blocks": ["x_t = a_t + b_t"]},
        {"doc_id": "p", "chunk_id": "c_results", "section": "Empirical Results", "text": "data sample regression result robustness", "formula_blocks": []},
        {"doc_id": "p", "chunk_id": "c_limits", "section": "Conclusion", "text": "limitations costs out-of-sample not disclosed", "formula_blocks": []},
        *({"doc_id": "p", "chunk_id": f"filler_{i}", "section": "Body", "text": "background", "formula_blocks": []} for i in range(20)),
    ]

    selected = select_reading_chunks(chunks, max_chunks=6)
    ids = {chunk["chunk_id"] for chunk in selected}

    assert "c_intro" in ids
    assert "c_formula" in ids
    assert "c_results" in ids
    assert "c_limits" in ids
    assert len(selected) == 6


def test_evidence_pack_v2_builds_new2_style_reading_tasks() -> None:
    chunks = [
        {"doc_id": "p", "chunk_id": "c_intro", "section": "Introduction", "text": "problem contribution market mechanism", "formula_blocks": []},
        {"doc_id": "p", "chunk_id": "c_formula", "section": "Model", "text": "where x is defined", "formula_blocks": ["x_t = a_t + b_t"]},
        {"doc_id": "p", "chunk_id": "c_results", "section": "Empirical Results", "text": "data sample regression result robustness", "formula_blocks": []},
        {"doc_id": "p", "chunk_id": "c_limits", "section": "Conclusion", "text": "limitations costs out-of-sample not disclosed", "formula_blocks": []},
    ]

    pack = build_evidence_pack_v2(chunks)
    tasks = build_reading_tasks_from_evidence_pack(pack, {"paper_id": "p", "title": "Paper"})

    assert pack["intro_claims"]
    assert pack["formula_evidence"][0]["formula_blocks"] == ["x_t = a_t + b_t"]
    assert pack["data_sample_evidence"]
    assert pack["conclusion_evidence"]
    assert [task["chunk_id"] for task in tasks] == ["overview_claims", "formula_variables", "method_data_results", "experimental_code", "conclusion_limits"]


def test_chunked_llm_reading_note_uses_map_merge_calls() -> None:
    class ChunkedFakeClient:
        def __init__(self) -> None:
            self.settings = LLMSettings(base_url="https://example.invalid", api_key="fake-key", model="fake-model")
            self.calls = 0
            self.messages: list[list[dict[str, str]]] = []

        def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
            self.calls += 1
            self.messages.append(messages)
            if "chunk reader" in messages[0]["content"]:
                return {
                    "schema_version": "reading_note_chunk_v1",
                    "chunk_id": "chunk",
                    "central_claims": ["chunk: high-frequency mechanism"],
                    "core_formulas": ["chunk: x_t = a_t + b_t"],
                    "not_disclosed": ["cost"],
                }
            return {
                "schema_version": "reading_note_v1",
                "paper_id": "paper_lob",
                "paper_title": "Limit Order Book Pressure",
                "source_url": "https://arxiv.org/abs/0000.00000",
                "source_type": "paper",
                "research_question": "chunk: question",
                "market_setting": "chunk: setting",
                "data_used": "chunk: data",
                "main_mechanism": "chunk: mechanism",
                "mechanism_chain": ["chunk: mechanism chain"],
                "core_formulas": ["chunk: x_t = a_t + b_t"],
                "variable_definitions": [],
                "empirical_findings": [],
                "limitations": ["chunk: cost 输入未披露"],
                "possible_trading_intuitions": ["chunk: intuition"],
                "supporting_evidence": [
                    {"evidence_id": "ev1", "chunk_id": "paper_lob::chunk_0001", "quote": "mechanism", "section": "Mechanism", "page": None, "why_relevant": "supports mechanism"}
                ],
                "not_disclosed": ["cost"],
                "score_dimensions": {
                    "relevance": {"score": 7},
                    "mechanism": {"score": 7},
                    "statistical": {"score": 4},
                    "implementation": {"score": 6},
                    "cost_sensitivity": {"score": 3},
                    "generality": {"score": 5},
                },
            }

    client = ChunkedFakeClient()
    note = build_llm_reading_note(_chunks(), client, max_chunks=1, chunked=True)  # type: ignore[arg-type]

    validate_reading_note(note)
    assert client.calls == 6
    task_payloads = [messages[1]["content"] for messages in client.messages[:-1]]
    assert any("overview_claims" in payload for payload in task_payloads)
    assert any("formula_variables" in payload for payload in task_payloads)
    assert any("method_data_results" in payload for payload in task_payloads)
    assert any("experimental_code" in payload for payload in task_payloads)
    assert any("conclusion_limits" in payload for payload in task_payloads)
    assert note["recommendation_score"] == 5.33


def test_chunked_merge_falls_back_to_chunk_evidence_and_scores() -> None:
    class MissingMergeFieldsClient:
        def __init__(self) -> None:
            self.settings = LLMSettings(base_url="https://example.invalid", api_key="fake-key", model="fake-model")
            self.calls = 0

        def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
            self.calls += 1
            if "chunk reader" in messages[0]["content"]:
                return {
                    "schema_version": "reading_note_chunk_v1",
                    "chunk_id": "paper_lob::chunk_0001",
                    "reading_task": "formula_variables",
                    "central_claims": ["paper_lob::chunk_0001: order book imbalance predicts intraday returns"],
                    "core_formulas": ["paper_lob::chunk_0001: I_t = (bidV1_t - askV1_t) / (bidV1_t + askV1_t)"],
                    "data_and_empirical_setup": ["sample is 输入未披露"],
                    "limitations": ["cost and out-of-sample evidence are 输入未披露"],
                    "not_disclosed": ["sample", "cost", "out_of_sample"],
                }
            return {
                "schema_version": "reading_note_v1",
                "research_question": "Does order book imbalance predict intraday returns?",
                "market_setting": "High-frequency order book market",
                "data_used": "输入未披露",
                "main_mechanism": "Visible depth imbalance creates short-horizon pressure.",
                "mechanism_chain": ["depth imbalance -> pressure -> short-horizon return"],
                "core_formulas": ["I_t = (bidV1_t - askV1_t) / (bidV1_t + askV1_t)"],
                "variable_definitions": [],
                "empirical_findings": [],
                "limitations": ["cost and out-of-sample evidence are 输入未披露"],
                "possible_trading_intuitions": ["book imbalance may be an HF pressure intuition"],
                "supporting_evidence": [],
                "not_disclosed": ["sample", "cost", "out_of_sample"],
                "score_dimensions": {},
            }

    note = build_llm_reading_note(_chunks(), MissingMergeFieldsClient(), max_chunks=1, chunked=True)  # type: ignore[arg-type]
    gate = evaluate_reading_gate(note, ReadingGateConfig(min_recommendation_score=5.5))

    validate_reading_note(note)
    assert note["supporting_evidence"]
    assert note["recommendation_score"] >= 5.5
    assert gate.should_continue is True