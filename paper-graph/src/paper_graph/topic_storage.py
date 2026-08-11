"""Versioned local storage for generated topic graphs and provider evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TopicGraphStore:
    """Read generated topic graphs without triggering network access."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.graphs = self.root / "graphs"

    def taxonomy(self) -> dict[str, Any]:
        return self._read(self.root / "taxonomy.json")

    def graph(self, topic_id: str) -> dict[str, Any] | None:
        path = self.graphs / f"topic_{topic_id}.json"
        return self._read(path) if path.exists() else None

    def summary(self) -> dict[str, Any]:
        path = self.root / "summary.json"
        return self._read(path) if path.exists() else {}

    def variant(self, topic_id: str, variant_id: str) -> dict[str, Any] | None:
        path = self.root / "variants" / topic_id / f"{variant_id}.json"
        return self._read(path) if path.exists() else None

    def variants(self, topic_id: str) -> list[dict[str, Any]]:
        directory = self.root / "variants" / topic_id
        if not directory.exists():
            return []
        return [self._read(path) for path in sorted(directory.glob("*.json"))]

    def save_variant(self, topic_id: str, variant_id: str, graph: dict[str, Any]) -> None:
        path = self.root / "variants" / topic_id / f"{variant_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError(f"expected object in {path}")
        return payload
