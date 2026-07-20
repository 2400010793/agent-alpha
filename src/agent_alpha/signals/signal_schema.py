from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


VALID_DIRECTIONS = {"positive", "negative", "conditional", "unknown"}
REQUIRED_ALPHA_SIGNAL_FIELDS = (
	"signal_id",
	"source_paper_id",
	"source_reading_note_id",
	"signal_name",
	"market_intuition",
	"hypothesis",
	"expected_direction",
	"hf_mechanism_tags",
	"candidate_fields",
	"evidence_ids",
	"created_at",
)


def utc_now_iso() -> str:
	return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AlphaSignal:
	signal_id: str
	source_paper_id: str
	source_reading_note_id: str
	signal_name: str
	market_intuition: str
	hypothesis: str
	expected_direction: str
	hf_mechanism_tags: list[str]
	candidate_fields: list[str]
	evidence_ids: list[str]
	created_at: str = field(default_factory=utc_now_iso)
	schema_version: str = "alpha_signal_v1"

	@classmethod
	def from_mapping(cls, payload: dict[str, Any]) -> "AlphaSignal":
		return cls(
			signal_id=str(payload.get("signal_id") or ""),
			source_paper_id=str(payload.get("source_paper_id") or ""),
			source_reading_note_id=str(payload.get("source_reading_note_id") or payload.get("source_paper_id") or ""),
			signal_name=str(payload.get("signal_name") or payload.get("signal_id") or ""),
			market_intuition=str(payload.get("market_intuition") or ""),
			hypothesis=str(payload.get("hypothesis") or ""),
			expected_direction=str(payload.get("expected_direction") or "unknown"),
			hf_mechanism_tags=[str(item) for item in payload.get("hf_mechanism_tags", [])],
			candidate_fields=[str(item) for item in payload.get("candidate_fields", [])],
			evidence_ids=[str(item) for item in payload.get("evidence_ids", [])],
			created_at=str(payload.get("created_at") or utc_now_iso()),
			schema_version=str(payload.get("schema_version") or "alpha_signal_v1"),
		)

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)


def validate_alpha_signal(signal: dict[str, Any]) -> None:
	missing = [field_name for field_name in REQUIRED_ALPHA_SIGNAL_FIELDS if field_name not in signal]
	if missing:
		raise ValueError(f"AlphaSignal missing fields: {missing}")
	if signal.get("schema_version", "alpha_signal_v1") != "alpha_signal_v1":
		raise ValueError("AlphaSignal schema_version must be alpha_signal_v1")
	for field_name in ("signal_id", "source_paper_id", "source_reading_note_id", "signal_name", "market_intuition", "hypothesis", "expected_direction", "created_at"):
		if not isinstance(signal.get(field_name), str):
			raise ValueError(f"AlphaSignal field must be a string: {field_name}")
	if not signal["signal_id"].strip():
		raise ValueError("AlphaSignal signal_id must be non-empty")
	if signal["expected_direction"] not in VALID_DIRECTIONS:
		raise ValueError(f"AlphaSignal expected_direction must be one of {sorted(VALID_DIRECTIONS)}")
	for field_name in ("hf_mechanism_tags", "candidate_fields", "evidence_ids"):
		value = signal.get(field_name)
		if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
			raise ValueError(f"AlphaSignal field must be list[str]: {field_name}")


__all__ = ["AlphaSignal", "REQUIRED_ALPHA_SIGNAL_FIELDS", "validate_alpha_signal"]