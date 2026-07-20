from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_alpha.rag.field_registry import FieldRegistry
from agent_alpha.signals.signal_schema import AlphaSignal, validate_alpha_signal
from agent_alpha.taxonomy.hf_taxonomy import load_hf_mechanisms


@dataclass(frozen=True)
class SignalQualification:
    ok: bool
    signal: dict[str, Any] | None = None
    message: str = ""


def allowed_mechanism_tags() -> set[str]:
    return {str(item.get("id")) for item in load_hf_mechanisms() if item.get("id")}


def allowed_candidate_fields(registry: FieldRegistry | None = None) -> set[str]:
    registry = registry or FieldRegistry.from_yaml()
    return (registry.allowed_input_fields | registry.derived_feature_fields) - registry.label_fields - registry.blocked_fields


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def qualify_alpha_signal_payload(
    payload: dict[str, Any],
    *,
    parent_signal: dict[str, Any] | None = None,
    registry: FieldRegistry | None = None,
) -> SignalQualification:
    parent_signal = parent_signal or {}
    registry = registry or FieldRegistry.from_yaml()
    allowed_tags = allowed_mechanism_tags()
    allowed_fields = allowed_candidate_fields(registry)
    signal_payload = dict(payload)
    signal_payload.setdefault("schema_version", "alpha_signal_v1")
    signal_payload.setdefault("source_paper_id", parent_signal.get("source_paper_id", ""))
    signal_payload.setdefault("source_reading_note_id", parent_signal.get("source_reading_note_id", parent_signal.get("source_paper_id", "")))
    signal_payload.setdefault("evidence_ids", parent_signal.get("evidence_ids", []))
    signal_payload["hf_mechanism_tags"] = [tag for tag in _as_str_list(signal_payload.get("hf_mechanism_tags")) if tag in allowed_tags]
    signal_payload["candidate_fields"] = [field for field in _as_str_list(signal_payload.get("candidate_fields")) if field in allowed_fields]
    try:
        signal = AlphaSignal.from_mapping(signal_payload).to_dict()
        validate_alpha_signal(signal)
    except (TypeError, ValueError) as exc:
        return SignalQualification(ok=False, message=str(exc))
    if not signal["market_intuition"].strip() or not signal["hypothesis"].strip():
        return SignalQualification(ok=False, message="signal market_intuition and hypothesis must be non-empty")
    return SignalQualification(ok=True, signal=signal, message="ok")


__all__ = ["SignalQualification", "allowed_candidate_fields", "allowed_mechanism_tags", "qualify_alpha_signal_payload"]