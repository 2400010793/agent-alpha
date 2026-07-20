from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_alpha.config import load_yaml


@dataclass(frozen=True)
class PaperSource:
    id: str
    type: str
    enabled: bool = True
    url: str = ""
    paths: tuple[str, ...] = ()
    source_name: str = ""
    source_type: str = "paper"
    query: str = ""
    max_items: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperSourceConfig:
    defaults: dict[str, Any]
    sources: tuple[PaperSource, ...]

    @property
    def enabled_sources(self) -> tuple[PaperSource, ...]:
        return tuple(source for source in self.sources if source.enabled)


def load_paper_sources(path: str | Path = "configs/paper_sources.yaml") -> PaperSourceConfig:
    payload = load_yaml(path)
    defaults = dict(payload.get("defaults", {}))
    sources: list[PaperSource] = []
    for item in payload.get("sources", []):
        if not isinstance(item, dict):
            raise ValueError("each paper source must be a mapping")
        known = {
            "id",
            "type",
            "enabled",
            "url",
            "paths",
            "source_name",
            "source_type",
            "query",
            "max_items",
        }
        source_id = str(item.get("id", "")).strip()
        source_type = str(item.get("type", "")).strip()
        if not source_id or not source_type:
            raise ValueError(f"paper source requires id and type: {item}")
        paths = tuple(str(path_item) for path_item in item.get("paths", []) or [])
        sources.append(
            PaperSource(
                id=source_id,
                type=source_type,
                enabled=bool(item.get("enabled", True)),
                url=str(item.get("url", "")),
                paths=paths,
                source_name=str(item.get("source_name", source_id)),
                source_type=str(item.get("source_type", "paper")),
                query=str(item.get("query", "")),
                max_items=int(item["max_items"]) if item.get("max_items") is not None else None,
                extra={key: value for key, value in item.items() if key not in known},
            )
        )
    return PaperSourceConfig(defaults=defaults, sources=tuple(sources))