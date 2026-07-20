from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_alpha.config import load_yaml


@dataclass(frozen=True)
class FieldRegistry:
    allowed_input_fields: frozenset[str]
    derived_feature_fields: frozenset[str]
    label_fields: frozenset[str]
    blocked_fields: frozenset[str]
    allowed_functions: frozenset[str]
    time_column: str = "delay_time"

    @classmethod
    def from_yaml(cls, path: str | Path = "configs/field_registry.yaml") -> "FieldRegistry":
        payload = load_yaml(path)
        return cls(
            allowed_input_fields=frozenset(str(x) for x in payload.get("allowed_input_fields", [])),
            derived_feature_fields=frozenset(str(x) for x in payload.get("derived_feature_fields", [])),
            label_fields=frozenset(str(x) for x in payload.get("label_fields", [])),
            blocked_fields=frozenset(str(x) for x in payload.get("blocked_fields", [])),
            allowed_functions=frozenset(str(x) for x in payload.get("allowed_functions", [])),
            time_column=str(payload.get("time_column", "delay_time")),
        )

    @property
    def readable_fields(self) -> frozenset[str]:
        return self.allowed_input_fields | self.derived_feature_fields | {self.time_column}

    def is_allowed_input(self, field: str) -> bool:
        return field in self.allowed_input_fields or field in self.derived_feature_fields

    def is_label(self, field: str) -> bool:
        return field in self.label_fields

    def is_blocked(self, field: str) -> bool:
        return field in self.blocked_fields