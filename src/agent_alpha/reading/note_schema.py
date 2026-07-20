from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SupportingEvidence:
    evidence_id: str
    chunk_id: str
    quote: str
    section: str
    page: int | None
    why_relevant: str


@dataclass(frozen=True)
class ReadingNoteV1:
    schema_version: str
    paper_id: str
    paper_title: str
    source_url: str
    source_type: str
    research_question: str
    market_setting: str
    data_used: str
    main_mechanism: str
    mechanism_chain: list[str] = field(default_factory=list)
    core_formulas: list[str] = field(default_factory=list)
    variable_definitions: list[str] = field(default_factory=list)
    empirical_findings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    possible_trading_intuitions: list[str] = field(default_factory=list)
    supporting_evidence: list[SupportingEvidence] = field(default_factory=list)
    not_disclosed: list[str] = field(default_factory=list)
    created_at: str = ""


REQUIRED_NOTE_KEYS = {
    "schema_version",
    "paper_id",
    "paper_title",
    "source_url",
    "source_type",
    "research_question",
    "market_setting",
    "data_used",
    "main_mechanism",
    "mechanism_chain",
    "core_formulas",
    "variable_definitions",
    "empirical_findings",
    "limitations",
    "possible_trading_intuitions",
    "supporting_evidence",
    "not_disclosed",
    "created_at",
}


def validate_reading_note(payload: dict[str, Any]) -> None:
    missing = REQUIRED_NOTE_KEYS - set(payload)
    if missing:
        raise ValueError(f"reading_note_v1 missing keys: {sorted(missing)}")
    if payload.get("schema_version") != "reading_note_v1":
        raise ValueError("reading note schema_version must be reading_note_v1")
    for item in payload.get("supporting_evidence", []):
        for key in {"evidence_id", "chunk_id", "quote", "section", "page", "why_relevant"}:
            if key not in item:
                raise ValueError(f"supporting evidence missing key: {key}")