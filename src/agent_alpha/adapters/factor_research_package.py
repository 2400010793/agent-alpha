"""Validate Paper Graph intake packages and adapt them to graph research v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agent_alpha.data_interfaces.data_contracts import DataContractV1
from agent_alpha.graph_research.ids import deterministic_id, sha256_content_hash


def load_json_object(path: str | Path) -> dict[str, Any]:
	payload = json.loads(Path(path).read_text(encoding="utf-8"))
	if not isinstance(payload, dict):
		raise ValueError(f"expected JSON object: {path}")
	return payload


def validate_factor_research_package(
	package: Mapping[str, Any],
	opportunity: Mapping[str, Any],
	data_contract: DataContractV1,
) -> None:
	if package.get("schema_version") != "factor_research_package_v1":
		raise ValueError("unsupported factor research package schema_version")
	if opportunity.get("schema_version") != "research_opportunity_v1":
		raise ValueError("unsupported research opportunity schema_version")
	if opportunity.get("status") != "READY":
		raise ValueError("Agent Alpha accepts only READY research opportunities")
	if package.get("research_opportunity_id") != opportunity.get("research_opportunity_id"):
		raise ValueError("package and opportunity IDs differ")
	if package.get("research_opportunity_hash") != sha256_content_hash(opportunity):
		raise ValueError("research opportunity content hash mismatch")
	graph_ref = package.get("graph_snapshot_ref") or {}
	for package_name, opportunity_name in (
		("graph_id", "graph_id"),
		("graph_version", "graph_version"),
		("graph_content_hash", "graph_content_hash"),
	):
		if graph_ref.get(package_name) != opportunity.get(opportunity_name):
			raise ValueError(f"graph snapshot mismatch: {package_name}")
	if package.get("target_track") not in opportunity.get("target_tracks", []):
		raise ValueError("package target track is not authorized by opportunity")
	if package.get("data_contract_id") != data_contract.data_contract_id:
		raise ValueError("package data contract ID does not match local contract")
	if package.get("data_contract_hash") != data_contract.contract_hash:
		raise ValueError("package data contract hash does not match local contract")
	if package.get("target_track") != data_contract.track:
		raise ValueError("package target track does not match data contract track")
	data_contract.validate_observables(opportunity.get("required_observables", []))
	package_artifacts = list(package.get("paper_artifact_refs") or [])
	opportunity_artifacts = list(opportunity.get("structured_artifact_refs") or [])
	if package_artifacts != opportunity_artifacts:
		raise ValueError("package paper artifact refs differ from opportunity")
	expected_evidence_hash = sha256_content_hash({
		"artifacts": opportunity_artifacts,
		"relations": list(opportunity.get("relation_refs") or []),
	})
	if package.get("evidence_bundle_hash") != expected_evidence_hash:
		raise ValueError("evidence bundle hash mismatch")


def adapt_factor_research_package(
	package: Mapping[str, Any],
	opportunity: Mapping[str, Any],
	data_contract: DataContractV1,
) -> dict[str, Any]:
	"""Return the existing GraphResearchGate input without weakening provenance."""

	validate_factor_research_package(package, opportunity, data_contract)
	seed_ids = [str(value) for value in opportunity.get("seed_paper_ids") or []]
	neighbor_ids = [str(value) for value in opportunity.get("neighbor_paper_ids") or []]
	all_ids = list(dict.fromkeys([*seed_ids, *neighbor_ids]))
	artifacts = {
		str(value.get("paper_id")): value
		for value in opportunity.get("structured_artifact_refs") or []
		if value.get("paper_id")
	}
	evidence_spans = []
	for paper_id, artifact in artifacts.items():
		for evidence_id in artifact.get("evidence_ids") or []:
			evidence_spans.append({
				"evidence_id": str(evidence_id),
				"canonical_paper_id": paper_id,
				"content_hash": str(artifact.get("content_hash") or ""),
				"source_artifact_id": str(artifact.get("artifact_id") or ""),
				"document_version": str(artifact.get("document_version") or ""),
			})
	relation_edges = []
	for relation in opportunity.get("relation_refs") or []:
		relation_edges.append({
			"relation_type": relation.get("relation_type"),
			"source_paper_id": relation.get("source_paper_id"),
			"target_paper_id": relation.get("target_paper_id"),
			"source_claim_id": relation.get("source_claim_id"),
			"target_claim_id": relation.get("target_claim_id"),
			"source_evidence_ids": list(relation.get("source_evidence_ids") or []),
			"target_evidence_ids": list(relation.get("target_evidence_ids") or []),
			"directed": True,
			"provenance": {
				"relation_id": relation.get("relation_id"),
				"review_status": relation.get("review_status", "verified"),
				"scope_alignment": relation.get("scope_alignment"),
			},
		})
	graph_ref = dict(package["graph_snapshot_ref"])
	return {
		"schema_version": "paper_graph_research_input_v1",
		"graph_id": str(opportunity["graph_id"]),
		"graph_version": str(opportunity["graph_version"]),
		"graph_artifact_id": deterministic_id("graphartifact", graph_ref),
		"graph_content_hash": str(opportunity["graph_content_hash"]),
		"snapshot_id": str(opportunity["as_of_date"]),
		"config_hash": str(opportunity["config_hash"]),
		"producer_revision": str(opportunity["producer_revision"]),
		"seed_paper_ids": seed_ids,
		"paper_nodes": [
			{
				"canonical_paper_id": paper_id,
				"identity_method": "canonical_contract",
				"structured_artifact_id": artifacts.get(paper_id, {}).get("artifact_id"),
			}
			for paper_id in all_ids
		],
		"relation_edges": relation_edges,
		"research_question": str(opportunity["research_question"]),
		"graph_selection_reason": ";".join(opportunity.get("selection_reasons") or []),
		"evidence_bundle_id": deterministic_id("ebundle", {
			"package_id": package["package_id"],
			"evidence_bundle_hash": package["evidence_bundle_hash"],
		}),
		"evidence_content_hash": str(package["evidence_bundle_hash"]),
		"evidence_spans": evidence_spans,
		"structural_only": False,
		"single_paper_baseline": len(all_ids) == 1,
		"factor_research_package": {
			"package_id": package["package_id"],
			"target_track": package["target_track"],
			"data_contract_id": package["data_contract_id"],
			"data_contract_hash": package["data_contract_hash"],
			"field_registry_version": package["field_registry_version"],
			"operator_registry_version": package["operator_registry_version"],
			"memory_snapshot_id": package["memory_snapshot_id"],
			"research_budget": dict(package.get("research_budget") or {}),
		},
	}


__all__ = [
	"adapt_factor_research_package",
	"load_json_object",
	"validate_factor_research_package",
]
