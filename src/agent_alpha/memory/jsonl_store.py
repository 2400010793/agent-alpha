from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from agent_alpha.config import project_path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_store_path(path: str | Path) -> Path:
    store_path = Path(path)
    if not store_path.is_absolute():
        store_path = project_path(str(store_path))
    return store_path


def _json_default(value: Any) -> str:
    return str(value)


def _matches_filter(value: Any, expected: Any) -> bool:
    if isinstance(expected, (list, tuple, set, frozenset)):
        return value in expected or bool(isinstance(value, list) and set(value).intersection(set(expected)))
    if isinstance(value, list):
        return expected in value
    return value == expected


@dataclass
class JsonlStore:
    path: str | Path
    schema_version: str
    id_field: str
    default_search_fields: tuple[str, ...] = field(default_factory=tuple)

    @property
    def resolved_path(self) -> Path:
        return resolve_store_path(self.path)

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        payload.setdefault("schema_version", self.schema_version)
        payload.setdefault(self.id_field, uuid.uuid4().hex)
        payload.setdefault("created_at", utc_now_iso())
        payload.setdefault("updated_at", payload["created_at"])
        out = self.resolved_path
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")
        return payload

    def load(self, *, filters: dict[str, Any] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        path = self.resolved_path
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL record at {path}:{line_number}") from exc
                if not isinstance(payload, dict):
                    raise ValueError(f"JSONL record must be an object at {path}:{line_number}")
                if filters and not all(_matches_filter(payload.get(key), expected) for key, expected in filters.items()):
                    continue
                records.append(payload)
                if limit is not None and len(records) >= limit:
                    break
        return records

    def search(
        self,
        query: str = "",
        *,
        filters: dict[str, Any] | None = None,
        fields: Iterable[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        terms = [term.casefold() for term in query.split() if term.strip()]
        search_fields = tuple(fields or self.default_search_fields)
        matches: list[dict[str, Any]] = []
        for record in self.load(filters=filters):
            haystack = self._search_text(record, search_fields)
            if terms and not all(term in haystack for term in terms):
                continue
            matches.append(record)
            if len(matches) >= limit:
                break
        return matches

    @staticmethod
    def _search_text(record: dict[str, Any], fields: tuple[str, ...]) -> str:
        if not fields:
            return json.dumps(record, ensure_ascii=False, sort_keys=True, default=_json_default).casefold()
        values = [record.get(field) for field in fields]
        return json.dumps(values, ensure_ascii=False, sort_keys=True, default=_json_default).casefold()