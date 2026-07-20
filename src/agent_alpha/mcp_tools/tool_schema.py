from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ToolEnvelope:
    request_id: str
    tool_name: str
    query: dict[str, Any]
    results: Any
    source_ids: list[str] = field(default_factory=list)
    permissions: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "tool_envelope_v1"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "schema_version": self.schema_version,
            "query": self.query,
            "results": self.results,
            "source_ids": self.source_ids,
            "permissions": self.permissions,
            "created_at": self.created_at,
        }