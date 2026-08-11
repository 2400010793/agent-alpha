from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from .ids import canonical_json, deterministic_id


def _utc_timestamp(value: str) -> str:
	if not isinstance(value, str) or not value.strip():
		raise ValueError("created_at must be a non-empty UTC timestamp")
	try:
		parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
	except ValueError:
		raise ValueError("created_at must be a valid UTC timestamp") from None
	if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
		raise ValueError("created_at must use the UTC timezone")
	return value


def _frozen_payload(value: Mapping[str, Any]) -> Mapping[str, Any]:
	if not isinstance(value, Mapping):
		raise TypeError("event payload must be a mapping")
	# Canonical JSON provides a deep, JSON-safe copy and rejects NaN/Infinity.
	return _freeze(json.loads(canonical_json(value)))


def _freeze(value: Any) -> Any:
	if isinstance(value, dict):
		return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
	if isinstance(value, list):
		return tuple(_freeze(item) for item in value)
	return value


@dataclass(frozen=True)
class ResearchEvent:
	schema_version: str
	event_id: str
	research_run_id: str
	sequence: int
	event_type: str
	payload: Mapping[str, Any]
	previous_event_id: str
	created_at: str

	def __post_init__(self) -> None:
		for name in ("schema_version", "event_id", "research_run_id", "event_type"):
			value = getattr(self, name)
			if not isinstance(value, str) or not value.strip():
				raise ValueError(f"{name} must be a non-empty string")
		if self.schema_version != "graph_research_event_v1":
			raise ValueError(f"unsupported research event schema: {self.schema_version}")
		if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 1:
			raise ValueError("sequence must be a positive integer")
		if not isinstance(self.previous_event_id, str):
			raise ValueError("previous_event_id must be a string")
		object.__setattr__(self, "payload", _frozen_payload(self.payload))
		object.__setattr__(self, "created_at", _utc_timestamp(self.created_at))
		expected = self.make_id(
			research_run_id=self.research_run_id,
			sequence=self.sequence,
			event_type=self.event_type,
			payload=self.payload,
			previous_event_id=self.previous_event_id,
		)
		if self.event_id != expected:
			raise ValueError("event_id does not match immutable event content")

	@staticmethod
	def make_id(
		*, research_run_id: str, sequence: int, event_type: str,
		payload: Mapping[str, Any], previous_event_id: str,
	) -> str:
		return deterministic_id(
			"grevent",
			{
				"research_run_id": research_run_id,
				"sequence": sequence,
				"event_type": event_type,
				"payload": payload,
				"previous_event_id": previous_event_id,
			},
		)

	@classmethod
	def create(
		cls, *, research_run_id: str, sequence: int, event_type: str,
		payload: Mapping[str, Any], previous_event_id: str = "", created_at: str,
	) -> "ResearchEvent":
		event_id = cls.make_id(
			research_run_id=research_run_id, sequence=sequence, event_type=event_type,
			payload=payload, previous_event_id=previous_event_id,
		)
		return cls(
			schema_version="graph_research_event_v1", event_id=event_id,
			research_run_id=research_run_id, sequence=sequence, event_type=event_type,
			payload=payload, previous_event_id=previous_event_id, created_at=created_at,
		)

	@classmethod
	def from_dict(cls, payload: Mapping[str, Any]) -> "ResearchEvent":
		return cls(
			schema_version=str(payload.get("schema_version") or ""),
			event_id=str(payload.get("event_id") or ""),
			research_run_id=str(payload.get("research_run_id") or ""),
			sequence=payload.get("sequence"),  # type: ignore[arg-type]
			event_type=str(payload.get("event_type") or ""),
			payload=payload.get("payload"),  # type: ignore[arg-type]
			previous_event_id=str(payload.get("previous_event_id") or ""),
			created_at=str(payload.get("created_at") or ""),
		)

	def to_dict(self) -> dict[str, Any]:
		return {
			"schema_version": self.schema_version,
			"event_id": self.event_id,
			"research_run_id": self.research_run_id,
			"sequence": self.sequence,
			"event_type": self.event_type,
			"payload": json.loads(canonical_json(self.payload)),
			"previous_event_id": self.previous_event_id,
			"created_at": self.created_at,
		}


def validate_event_chain(events: tuple[ResearchEvent, ...] | list[ResearchEvent]) -> None:
	previous = ""
	run_id = ""
	for expected_sequence, event in enumerate(events, start=1):
		if event.sequence != expected_sequence:
			raise ValueError(f"event sequence gap at {expected_sequence}")
		if run_id and event.research_run_id != run_id:
			raise ValueError("event chain contains multiple research_run_ids")
		if event.previous_event_id != previous:
			raise ValueError(f"event chain mismatch at sequence {expected_sequence}")
		run_id = event.research_run_id
		previous = event.event_id


__all__ = ["ResearchEvent", "validate_event_chain"]
