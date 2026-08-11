from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from agent_alpha.factors.factor_schema import FactorCandidate


CANDIDATE_STATUSES = {
    "created",
    "validated",
    "rendered",
    "compiled",
    "evaluated",
    "accepted",
    "rejected",
    "mutated",
    "deprecated",
}


@dataclass(frozen=True)
class CandidatePoolRecord:
    candidate_id: str
    factor_id: str
    name: str
    prefix_expression_hash: str
    expression_hash: str
    source_signal_id: str
    source_reading_note_id: str
    mechanism_tags: list[str]
    parent_ids: list[str]
    generation: int
    status: str
    created_at: str
    updated_at: str
    research_run_id: str = ""
    graph_id: str = ""
    hypothesis_id: str = ""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _candidate_from_input(candidate: dict[str, Any] | FactorCandidate) -> FactorCandidate:
    if isinstance(candidate, FactorCandidate):
        return candidate
    return FactorCandidate.from_mapping(candidate)


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def _validate_status(status: str) -> None:
    if status not in CANDIDATE_STATUSES:
        allowed = ", ".join(sorted(CANDIDATE_STATUSES))
        raise ValueError(f"unknown candidate status: {status!r}; expected one of: {allowed}")


def prefix_expression_hash(candidate: dict[str, Any] | FactorCandidate) -> str:
    factor_candidate = _candidate_from_input(candidate)
    if factor_candidate.prefix_expression is None:
        return ""
    return _stable_hash(factor_candidate.prefix_expression)


def expression_hash(candidate: dict[str, Any] | FactorCandidate) -> str:
    factor_candidate = _candidate_from_input(candidate)
    return _stable_hash(factor_candidate.expression.strip())


def build_pool_record(
    candidate: dict[str, Any] | FactorCandidate,
    *,
    parent_ids: list[str] | None = None,
    generation: int = 0,
    status: str = "created",
) -> CandidatePoolRecord:
    _validate_status(status)
    factor_candidate = _candidate_from_input(candidate)
    prefix_hash = prefix_expression_hash(factor_candidate)
    expr_hash = expression_hash(factor_candidate)
    dedupe_hash = prefix_hash or expr_hash
    now = _utc_now_iso()
    scoped_id = _stable_hash(
        {
            "definition": dedupe_hash,
            "research_run_id": factor_candidate.research_run_id,
            "graph_id": factor_candidate.graph_id,
            "hypothesis_id": factor_candidate.hypothesis_id,
        }
    )
    return CandidatePoolRecord(
        candidate_id=f"cand_{scoped_id}",
        factor_id=factor_candidate.factor_id,
        name=factor_candidate.name,
        prefix_expression_hash=prefix_hash,
        expression_hash=expr_hash,
        source_signal_id=factor_candidate.source_signal_id,
        source_reading_note_id=factor_candidate.source_reading_note_id,
        mechanism_tags=list(factor_candidate.mechanism_tags),
        parent_ids=list(parent_ids or []),
        generation=int(generation),
        status=status,
        created_at=now,
        updated_at=now,
        research_run_id=factor_candidate.research_run_id,
        graph_id=factor_candidate.graph_id,
        hypothesis_id=factor_candidate.hypothesis_id,
    )
 

def deduplicate_candidates(candidates: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    deduplicated: list[dict] = []
    for candidate in candidates:
        prefix_hash = prefix_expression_hash(candidate)
        expr_hash = expression_hash(candidate)
        key = ("prefix", prefix_hash) if prefix_hash else ("expression", expr_hash)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(candidate)
    return deduplicated


class CandidatePool:
    def __init__(self, records: list[CandidatePoolRecord] | None = None):
        self._records: list[CandidatePoolRecord] = []
        self._by_candidate_id: dict[str, CandidatePoolRecord] = {}
        self._by_dedupe_key: dict[tuple[str, str], CandidatePoolRecord] = {}
        for record in records or []:
            self._insert_record(record)

    @staticmethod
    def _dedupe_key(record: CandidatePoolRecord) -> tuple[str, str]:
        if record.prefix_expression_hash:
            return ("prefix", record.prefix_expression_hash)
        return ("expression", record.expression_hash)

    def _insert_record(self, record: CandidatePoolRecord) -> CandidatePoolRecord:
        _validate_status(record.status)
        key = self._dedupe_key(record)
        existing = self._by_dedupe_key.get(key)
        if existing is not None:
            return existing
        self._records.append(record)
        self._by_candidate_id[record.candidate_id] = record
        self._by_dedupe_key[key] = record
        return record

    def add(
        self,
        candidate: dict[str, Any] | FactorCandidate,
        *,
        parent_ids: list[str] | None = None,
        generation: int = 0,
        status: str = "created",
    ) -> CandidatePoolRecord:
        record = build_pool_record(candidate, parent_ids=parent_ids, generation=generation, status=status)
        return self._insert_record(record)

    def update_status(self, candidate_id: str, status: str) -> CandidatePoolRecord:
        _validate_status(status)
        record = self._by_candidate_id.get(candidate_id)
        if record is None:
            raise KeyError(f"unknown candidate_id: {candidate_id}")
        updated = replace(record, status=status, updated_at=_utc_now_iso())
        index = self._records.index(record)
        self._records[index] = updated
        self._by_candidate_id[candidate_id] = updated
        self._by_dedupe_key[self._dedupe_key(updated)] = updated
        return updated

    def by_status(self, status: str) -> list[CandidatePoolRecord]:
        _validate_status(status)
        return [record for record in self._records if record.status == status]

    def by_generation(self, generation: int) -> list[CandidatePoolRecord]:
        return [record for record in self._records if record.generation == generation]

    def to_jsonl(self, path: str | Path) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            for record in self._records:
                handle.write(json.dumps(asdict(record), sort_keys=True, ensure_ascii=False) + "\n")

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "CandidatePool":
        records: list[CandidatePoolRecord] = []
        input_path = Path(path)
        with input_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                records.append(CandidatePoolRecord(**json.loads(line)))
        return cls(records)


__all__ = [
    "CANDIDATE_STATUSES",
    "CandidatePool",
    "CandidatePoolRecord",
    "build_pool_record",
    "deduplicate_candidates",
    "expression_hash",
    "prefix_expression_hash",
]
