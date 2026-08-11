from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from agent_alpha.graph_research.ids import deterministic_id

from .evaluator import STAGES
from .features import RETURN_ONLY_OPERATORS


@dataclass(frozen=True)
class DailyExperimentSpecV1:
	daily_experiment_id: str
	package_id: str
	hypothesis_id: str
	factor_id: str
	operator: str
	window: int
	min_periods: int
	horizon: int
	direction: str
	stage: str
	date_start: str
	date_end: str
	min_cross_sectional_obs: int
	max_abs_return: float
	data_contract_id: str
	data_contract_hash: str
	operator_registry_version: str
	schema_version: str = "daily_experiment_spec_v1"

	def __post_init__(self) -> None:
		for name in (
			"daily_experiment_id", "package_id", "hypothesis_id", "factor_id",
			"operator", "direction", "stage", "date_start", "date_end",
			"data_contract_id", "data_contract_hash", "operator_registry_version",
		):
			if not str(getattr(self, name) or "").strip():
				raise ValueError(f"{name} must be non-empty")
		if self.schema_version != "daily_experiment_spec_v1":
			raise ValueError("unsupported daily experiment schema_version")
		if self.operator not in RETURN_ONLY_OPERATORS:
			raise ValueError("daily experiment uses an unapproved operator")
		if self.stage not in STAGES:
			raise ValueError("daily experiment uses an unsupported stage")
		if self.direction not in {"positive", "negative"}:
			raise ValueError("daily experiment direction must be positive or negative")
		if self.window < 2 or not 2 <= self.min_periods <= self.window:
			raise ValueError("invalid daily feature window/min_periods")
		if self.horizon < 1 or self.min_cross_sectional_obs < 5:
			raise ValueError("invalid daily horizon or minimum cross-sectional observations")
		expected = deterministic_id("dailyexp", self.identity_payload())
		if self.daily_experiment_id != expected:
			raise ValueError("daily_experiment_id does not match preregistration")

	def identity_payload(self) -> dict[str, Any]:
		return {
			key: value for key, value in asdict(self).items()
			if key not in {"daily_experiment_id", "schema_version"}
		}

	@classmethod
	def create(cls, **values: Any) -> "DailyExperimentSpecV1":
		payload = dict(values)
		payload.setdefault("schema_version", "daily_experiment_spec_v1")
		identity = {
			key: value for key, value in payload.items()
			if key not in {"daily_experiment_id", "schema_version"}
		}
		payload["daily_experiment_id"] = deterministic_id("dailyexp", identity)
		return cls(**payload)

	@classmethod
	def from_mapping(cls, value: Mapping[str, Any]) -> "DailyExperimentSpecV1":
		payload = dict(value)
		if payload.get("daily_experiment_id"):
			return cls(**payload)
		return cls.create(**payload)

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)


__all__ = ["DailyExperimentSpecV1"]
