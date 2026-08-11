from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Protocol, Sequence

from .ids import deterministic_id
from .models import DecisionRecord, ExperimentNodeV1, ExperimentReviewV1, HypothesisNodeV1, RunAttemptV1


@dataclass(frozen=True)
class EvidenceRecord:
	evidence_id: str
	canonical_paper_id: str
	content_hash: str
	text: str


@dataclass(frozen=True)
class ArtifactReference:
	artifact_id: str
	content_hash: str
	media_type: str


@dataclass(frozen=True)
class MetricRecord:
	metric_name: str
	experiment_id: str
	value: float
	source_artifact_id: str
	content_hash: str

	def __post_init__(self) -> None:
		for name in ("metric_name", "experiment_id", "source_artifact_id", "content_hash"):
			value = getattr(self, name)
			if not isinstance(value, str) or not value.strip():
				raise ValueError(f"{name} must be a non-empty string")
			object.__setattr__(self, name, value.strip())
		if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not math.isfinite(float(self.value)):
			raise ValueError("metric value must be finite")
		object.__setattr__(self, "value", float(self.value))

	@property
	def registry_key(self) -> str:
		return deterministic_id("metric", self.to_dict())

	def to_dict(self) -> dict[str, str | float]:
		return {
			"metric_name": self.metric_name, "experiment_id": self.experiment_id,
			"value": self.value, "source_artifact_id": self.source_artifact_id,
			"content_hash": self.content_hash,
		}


@dataclass(frozen=True)
class ExperimentReviewResult:
	review: ExperimentReviewV1
	metrics: tuple[MetricRecord, ...]

	def __post_init__(self) -> None:
		if not isinstance(self.review, ExperimentReviewV1):
			raise TypeError("review must be ExperimentReviewV1")
		if not isinstance(self.metrics, tuple):
			raise TypeError("metrics must be tuple[MetricRecord, ...]")
		if any(not isinstance(metric, MetricRecord) for metric in self.metrics):
			raise TypeError("metrics must contain only MetricRecord values")


class EvidenceProvider(Protocol):
	def get_evidence(
		self, graph_id: str, graph_version: str, canonical_paper_ids: Sequence[str]
	) -> tuple[EvidenceRecord, ...]: ...


class CompletedRunLookup(Protocol):
	def is_completed(self, research_run_id: str) -> bool: ...


class HypothesisModel(Protocol):
	def propose(self, research_run_id: str, evidence: Sequence[EvidenceRecord]) -> tuple[HypothesisNodeV1, ...]: ...


class HumanApprovalPort(Protocol):
	def review(self, hypothesis: HypothesisNodeV1) -> DecisionRecord: ...


class ExperimentPlanner(Protocol):
	def plan(self, hypothesis: HypothesisNodeV1, budget_id: str) -> tuple[ExperimentNodeV1, ...]: ...


class ExperimentExecutor(Protocol):
	def execute(self, experiment: ExperimentNodeV1, attempt_number: int) -> RunAttemptV1: ...


class ExperimentReviewer(Protocol):
	def review(self, experiment: ExperimentNodeV1, attempt: RunAttemptV1) -> ExperimentReviewResult: ...


class ArtifactStore(Protocol):
	def put(self, artifact_id: str, content: bytes, media_type: str) -> ArtifactReference: ...


class MetricRegistry(Protocol):
	def register(self, metric: MetricRecord) -> MetricRecord: ...


class Clock(Protocol):
	def now(self) -> datetime: ...


__all__ = [
	"ArtifactReference", "ArtifactStore", "Clock", "CompletedRunLookup", "EvidenceProvider",
	"EvidenceRecord", "ExperimentExecutor", "ExperimentPlanner", "ExperimentReviewer",
	"ExperimentReviewResult", "HumanApprovalPort", "HypothesisModel", "MetricRecord", "MetricRegistry",
]
