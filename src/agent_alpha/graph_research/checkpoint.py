from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .events import ResearchEvent, validate_event_chain
from .ids import sha256_content_hash


class CheckpointCorruptionError(ValueError):
	pass


class ResearchCheckpointStore:
	"""Atomic, hash-verified event checkpoints partitioned by research run."""

	def __init__(self, root: str | Path) -> None:
		self.root = Path(root)

	def path_for(self, research_run_id: str) -> Path:
		if not isinstance(research_run_id, str) or not research_run_id.strip():
			raise ValueError("research_run_id must be non-empty")
		return self.root / research_run_id / "checkpoint.json"

	def exists(self, research_run_id: str) -> bool:
		return self.path_for(research_run_id).exists()

	def save(self, research_run_id: str, events: Iterable[ResearchEvent]) -> Path:
		event_list = list(events)
		validate_event_chain(event_list)
		if event_list and any(event.research_run_id != research_run_id for event in event_list):
			raise ValueError("checkpoint run ID does not match events")
		event_payloads = [event.to_dict() for event in event_list]
		envelope = {
			"schema_version": "graph_research_checkpoint_v1",
			"research_run_id": research_run_id,
			"event_count": len(event_payloads),
			"head_event_id": event_list[-1].event_id if event_list else "",
			"events_hash": sha256_content_hash(event_payloads),
			"events": event_payloads,
		}
		path = self.path_for(research_run_id)
		path.parent.mkdir(parents=True, exist_ok=True)
		tmp = path.with_suffix(path.suffix + ".tmp")
		tmp.write_text(json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
		tmp.replace(path)
		return path

	def load(self, research_run_id: str) -> tuple[ResearchEvent, ...]:
		path = self.path_for(research_run_id)
		if not path.exists():
			return ()
		try:
			envelope = json.loads(path.read_text(encoding="utf-8"))
		except (OSError, json.JSONDecodeError) as exc:
			raise CheckpointCorruptionError(f"cannot read checkpoint: {path}") from exc
		try:
			if envelope.get("schema_version") != "graph_research_checkpoint_v1":
				raise ValueError("unsupported checkpoint schema")
			if envelope.get("research_run_id") != research_run_id:
				raise ValueError("checkpoint research_run_id mismatch")
			raw_events = envelope.get("events")
			if not isinstance(raw_events, list):
				raise ValueError("checkpoint events must be a list")
			if envelope.get("event_count") != len(raw_events):
				raise ValueError("checkpoint event_count mismatch")
			if envelope.get("events_hash") != sha256_content_hash(raw_events):
				raise ValueError("checkpoint events_hash mismatch")
			events = tuple(ResearchEvent.from_dict(item) for item in raw_events)
			validate_event_chain(events)
			head = events[-1].event_id if events else ""
			if envelope.get("head_event_id") != head:
				raise ValueError("checkpoint head_event_id mismatch")
			return events
		except (AttributeError, TypeError, ValueError) as exc:
			raise CheckpointCorruptionError(str(exc)) from exc

	def append(self, event: ResearchEvent) -> Path:
		events = list(self.load(event.research_run_id))
		expected_sequence = len(events) + 1
		expected_previous = events[-1].event_id if events else ""
		if event.sequence != expected_sequence or event.previous_event_id != expected_previous:
			raise ValueError("event does not extend checkpoint head")
		events.append(event)
		return self.save(event.research_run_id, events)

	def export_jsonl(self, research_run_id: str, path: str | Path) -> Path:
		out = Path(path)
		out.parent.mkdir(parents=True, exist_ok=True)
		tmp = out.with_suffix(out.suffix + ".tmp")
		with tmp.open("w", encoding="utf-8") as handle:
			for event in self.load(research_run_id):
				handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
		tmp.replace(out)
		return out


__all__ = ["CheckpointCorruptionError", "ResearchCheckpointStore"]
