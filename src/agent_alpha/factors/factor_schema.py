from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class FactorCandidate:
    """Narrow schema for FactorCandidate -> fac-eval-compatible file."""

    factor_id: str
    name: str
    expression: str
    fields: list[str]
    prefix_expression: Any | None = None
    windows: list[int] = field(default_factory=list)
    direction: str = "unknown"
    source_signal_id: str = ""
    source_reading_note_id: str = ""
    mechanism_tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "FactorCandidate":
        factor_id = str(payload.get("factor_id") or payload.get("name") or payload.get("factor_name") or "").strip()
        name = str(payload.get("name") or payload.get("factor_name") or factor_id).strip()
        expression = str(payload.get("expression") or payload.get("factor_expression") or "").strip()
        prefix_expression = payload.get("prefix_expression")
        if not expression and prefix_expression is not None:
            from agent_alpha.factors.prefix_expression import prefix_to_expression

            expression = prefix_to_expression(prefix_expression)
        fields = [str(x) for x in payload.get("fields", [])]
        return cls(
            factor_id=factor_id or name,
            name=name or factor_id,
            expression=expression,
            fields=fields,
            prefix_expression=prefix_expression,
            windows=[int(x) for x in payload.get("windows", [])],
            direction=str(payload.get("direction") or payload.get("expected_direction") or "unknown"),
            source_signal_id=str(payload.get("source_signal_id") or ""),
            source_reading_note_id=str(payload.get("source_reading_note_id") or payload.get("source_paper_id") or ""),
            mechanism_tags=[str(x) for x in payload.get("mechanism_tags", payload.get("hf_mechanism_tags", []))],
            created_at=str(payload.get("created_at") or utc_now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

__all__ = ["FactorCandidate"]