from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_alpha.graph_research.checkpoint import CheckpointCorruptionError, ResearchCheckpointStore
from agent_alpha.graph_research.events import ResearchEvent


NOW = "2026-08-10T10:00:00+00:00"


def _event(sequence: int, previous: str = "") -> ResearchEvent:
	return ResearchEvent.create(
		research_run_id="grun_test", sequence=sequence, event_type="test_event",
		payload={"sequence": sequence}, previous_event_id=previous, created_at=NOW,
	)


def test_checkpoint_round_trip_and_jsonl_export(tmp_path: Path) -> None:
	store = ResearchCheckpointStore(tmp_path)
	first = _event(1)
	second = _event(2, first.event_id)

	store.append(first)
	store.append(second)
	exported = store.export_jsonl("grun_test", tmp_path / "stage_events.jsonl")

	assert store.load("grun_test") == (first, second)
	assert len(exported.read_text(encoding="utf-8").splitlines()) == 2
	with pytest.raises(TypeError):
		first.payload["nested"] = {}  # type: ignore[index]


def test_checkpoint_detects_content_tampering(tmp_path: Path) -> None:
	store = ResearchCheckpointStore(tmp_path)
	store.append(_event(1))
	path = store.path_for("grun_test")
	payload = json.loads(path.read_text(encoding="utf-8"))
	payload["events"][0]["payload"]["sequence"] = 999
	path.write_text(json.dumps(payload), encoding="utf-8")

	with pytest.raises(CheckpointCorruptionError, match="events_hash"):
		store.load("grun_test")


def test_checkpoint_rejects_non_extending_event(tmp_path: Path) -> None:
	store = ResearchCheckpointStore(tmp_path)
	first = _event(1)
	store.append(first)

	with pytest.raises(ValueError, match="extend checkpoint"):
		store.append(_event(2, "wrong_previous"))
