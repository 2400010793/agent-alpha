from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Set
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable


ID_DIGEST_LENGTH = 32
NO_EVIDENCE = "no_evidence"


def _sort_key(value: Any) -> str:
	return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonicalize(value: Any) -> Any:
	"""Return a JSON-safe canonical value without guessing list semantics.

	Mappings and sets are unordered and therefore normalized here. Lists and tuples
	retain order because paths, lineage, and windows can have scientific meaning.
	Identity collections must be sorted explicitly by their owning domain object.
	"""
	if isinstance(value, Enum):
		return canonicalize(value.value)
	if isinstance(value, datetime):
		if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
			raise ValueError("datetime values must be timezone-aware UTC")
		return value.isoformat()
	if isinstance(value, Mapping):
		return {str(key): canonicalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
	if isinstance(value, Set) and not isinstance(value, (str, bytes, bytearray)):
		items = [canonicalize(item) for item in value]
		return sorted(items, key=_sort_key)
	if isinstance(value, (list, tuple)):
		return [canonicalize(item) for item in value]
	if isinstance(value, float) and not math.isfinite(value):
		raise ValueError("NaN and Infinity are not permitted in canonical JSON")
	if value is None or isinstance(value, (str, int, float, bool)):
		return value
	raise TypeError("unsupported canonical JSON value: %s" % type(value).__name__)


def canonical_json(payload: Any) -> str:
	return json.dumps(
		canonicalize(payload),
		sort_keys=True,
		separators=(",", ":"),
		ensure_ascii=False,
		allow_nan=False,
	)


def sha256_content_hash(payload: Any) -> str:
	return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def deterministic_id(prefix: str, payload: Any, digest_length: int = ID_DIGEST_LENGTH) -> str:
	if not isinstance(prefix, str) or not prefix.strip():
		raise ValueError("ID prefix must be non-empty")
	if digest_length < 24 or digest_length > 64:
		raise ValueError("digest_length must be between 24 and 64")
	return "%s_%s" % (prefix.strip(), sha256_content_hash(payload)[:digest_length])


def normalize_identity_ids(values: Iterable[str], field_name: str = "identity IDs") -> tuple[str, ...]:
	if isinstance(values, (str, bytes)):
		raise ValueError("%s must be a collection of IDs" % field_name)
	normalized = []
	for value in values:
		if not isinstance(value, str) or not value.strip():
			raise ValueError("%s must contain only non-empty strings" % field_name)
		normalized.append(value.strip())
	return tuple(sorted(set(normalized)))


def research_run_id(
	*,
	graph_id: str,
	graph_version: str,
	graph_artifact_id: str,
	graph_content_hash: str,
	evidence_content_hash: str,
	research_config_hash: str,
	snapshot_id: str,
) -> str:
	payload = {
		"graph_id": _required(graph_id, "graph_id"),
		"graph_version": _required(graph_version, "graph_version"),
		"graph_artifact_id": _required(graph_artifact_id, "graph_artifact_id"),
		"graph_content_hash": _required(graph_content_hash, "graph_content_hash"),
		"evidence_content_hash": _required(evidence_content_hash, "evidence_content_hash"),
		"research_config_hash": _required(research_config_hash, "research_config_hash"),
		"snapshot_id": _required(snapshot_id, "snapshot_id"),
	}
	return deterministic_id("grun", payload)


def hypothesis_id(
	*,
	research_run_id: str,
	graph_id: str,
	statement: str,
	mechanism: str,
	prediction: str,
	source_paper_ids: Iterable[str],
	source_claim_ids: Iterable[str] = (),
	evidence_ids: Iterable[str] = (),
	relation_evidence_ids: Iterable[str] = (),
	structural_only: bool = False,
) -> str:
	payload = {
		"research_run_id": _required(research_run_id, "research_run_id"),
		"graph_id": _required(graph_id, "graph_id"),
		"statement": _required(statement, "statement"),
		"mechanism": _required(mechanism, "mechanism"),
		"prediction": _required(prediction, "prediction"),
		"source_paper_ids": normalize_identity_ids(source_paper_ids, "source_paper_ids"),
		"source_claim_ids": normalize_identity_ids(source_claim_ids, "source_claim_ids"),
		"evidence_ids": normalize_identity_ids(evidence_ids, "evidence_ids"),
		"relation_evidence_ids": normalize_identity_ids(relation_evidence_ids, "relation_evidence_ids"),
		"structural_only": bool(structural_only),
	}
	return deterministic_id("hyp", payload)


def experiment_id(*, hypothesis_id: str, experiment_version: int, preregistration: Mapping[str, Any]) -> str:
	if not isinstance(experiment_version, int) or isinstance(experiment_version, bool) or experiment_version < 1:
		raise ValueError("experiment_version must be a positive integer")
	return deterministic_id(
		"exp",
		{
			"hypothesis_id": _required(hypothesis_id, "hypothesis_id"),
			"experiment_version": experiment_version,
			"preregistration": preregistration,
		},
	)


def run_attempt_id(
	*, experiment_id: str, attempt_number: int, code_hash: str, environment_hash: str
) -> str:
	if not isinstance(attempt_number, int) or isinstance(attempt_number, bool) or attempt_number < 1:
		raise ValueError("attempt_number must be a positive integer")
	return deterministic_id(
		"attempt",
		{
			"experiment_id": _required(experiment_id, "experiment_id"),
			"attempt_number": attempt_number,
			"code_hash": _required(code_hash, "code_hash"),
			"environment_hash": _required(environment_hash, "environment_hash"),
		},
	)


def experiment_review_id(
	*, experiment_id: str, run_attempt_id: str, verdict: str,
	primary_metric_name: str, primary_metric_value: float | None,
	acceptance_rule: str, reason_codes: Iterable[str], metrics_content_hash: str,
	reviewer_revision: str,
) -> str:
	return deterministic_id(
		"review",
		{
			"experiment_id": _required(experiment_id, "experiment_id"),
			"run_attempt_id": _required(run_attempt_id, "run_attempt_id"),
			"verdict": _required(verdict, "verdict"),
			"primary_metric_name": _required(primary_metric_name, "primary_metric_name"),
			"primary_metric_value": primary_metric_value,
			"acceptance_rule": _required(acceptance_rule, "acceptance_rule"),
			"reason_codes": normalize_identity_ids(reason_codes, "reason_codes"),
			"metrics_content_hash": _required(metrics_content_hash, "metrics_content_hash"),
			"reviewer_revision": _required(reviewer_revision, "reviewer_revision"),
		},
	)


def budget_id(payload: Mapping[str, Any]) -> str:
	return deterministic_id("budget", payload)


def _required(value: str, field_name: str) -> str:
	if not isinstance(value, str) or not value.strip():
		raise ValueError("%s must be a non-empty string" % field_name)
	return value.strip()


# Readable aliases for callers that prefer generation verbs.
generate_research_run_id = research_run_id
generate_hypothesis_id = hypothesis_id
generate_experiment_id = experiment_id
generate_run_attempt_id = run_attempt_id
generate_experiment_review_id = experiment_review_id
generate_budget_id = budget_id
content_hash = sha256_content_hash


__all__ = [
	"ID_DIGEST_LENGTH",
	"NO_EVIDENCE",
	"budget_id",
	"canonical_json",
	"canonicalize",
	"content_hash",
	"deterministic_id",
	"experiment_id",
	"experiment_review_id",
	"generate_budget_id",
	"generate_experiment_id",
	"generate_experiment_review_id",
	"generate_hypothesis_id",
	"generate_research_run_id",
	"generate_run_attempt_id",
	"hypothesis_id",
	"normalize_identity_ids",
	"research_run_id",
	"run_attempt_id",
	"sha256_content_hash",
]
