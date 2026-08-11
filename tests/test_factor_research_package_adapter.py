from pathlib import Path

import pytest

from agent_alpha.adapters.factor_research_package import adapt_factor_research_package
from agent_alpha.data_interfaces.data_contracts import DataContractV1
from agent_alpha.graph_research.graph_gate import GraphResearchGate
from agent_alpha.graph_research.ids import sha256_content_hash
from agent_alpha.graph_research.states import GateStatus


def _contract() -> DataContractV1:
	return DataContractV1.from_mapping({
		"schema_version": "data_contract_v1",
		"data_contract_id": "daily_ret_wide_v1",
		"track": "daily_cross_sectional",
		"status": "active",
		"sources": [{"path": "/home/gaozh/ret.parquet"}],
		"allowed_observables": ["RETURN_HISTORY"],
		"blocked_observables": ["VOLUME_TURNOVER"],
		"access_policy": {"exact_paths": ["/home/gaozh/ret.parquet"]},
	})


def _opportunity() -> dict:
	return {
		"schema_version": "research_opportunity_v1",
		"research_opportunity_id": "opportunity:one",
		"as_of_date": "2026-08-11",
		"graph_id": "graph:momentum",
		"graph_version": "graph-v1",
		"graph_content_hash": "graphhash",
		"seed_paper_ids": ["arxiv:one"],
		"neighbor_paper_ids": [],
		"relation_refs": [],
		"structured_artifact_refs": [{
			"artifact_id": "artifact:one",
			"paper_id": "arxiv:one",
			"document_version": "v1",
			"content_hash": "paperhash",
			"claim_ids": ["claim:one"],
			"evidence_ids": ["evidence:one"],
		}],
		"research_question": "Does return-only momentum predict returns?",
		"selection_reasons": ["eligible"],
		"target_tracks": ["daily_cross_sectional"],
		"required_observables": ["RETURN_HISTORY"],
		"status": "READY",
		"producer_revision": "paper-graph-rev",
		"config_hash": "research-config",
	}


def _package(opportunity: dict, contract: DataContractV1) -> dict:
	artifacts = opportunity["structured_artifact_refs"]
	return {
		"schema_version": "factor_research_package_v1",
		"package_id": "researchpkg:one",
		"research_opportunity_id": opportunity["research_opportunity_id"],
		"research_opportunity_hash": sha256_content_hash(opportunity),
		"graph_snapshot_ref": {
			"graph_id": opportunity["graph_id"],
			"graph_version": opportunity["graph_version"],
			"graph_content_hash": opportunity["graph_content_hash"],
		},
		"paper_artifact_refs": artifacts,
		"evidence_bundle_hash": sha256_content_hash({"artifacts": artifacts, "relations": []}),
		"target_track": "daily_cross_sectional",
		"data_contract_id": contract.data_contract_id,
		"data_contract_hash": contract.contract_hash,
		"field_registry_version": "daily-fields-v1",
		"operator_registry_version": "daily-ops-v1",
		"memory_snapshot_id": "memory:empty",
		"research_budget": {"max_hypotheses": 2},
		"selection_trace": {"rank": 1},
	}


def test_adapter_builds_eligible_single_paper_graph_input() -> None:
	contract = _contract()
	opportunity = _opportunity()
	graph = adapt_factor_research_package(_package(opportunity, contract), opportunity, contract)
	assert graph["single_paper_baseline"] is True
	assert graph["factor_research_package"]["data_contract_id"] == "daily_ret_wide_v1"
	assert GraphResearchGate().evaluate(graph).status == GateStatus.ELIGIBLE


def test_adapter_rejects_observable_outside_contract() -> None:
	contract = _contract()
	opportunity = _opportunity()
	opportunity["required_observables"] = ["VOLUME_TURNOVER"]
	package = _package(opportunity, contract)
	with pytest.raises(ValueError, match="blocked observables"):
		adapt_factor_research_package(package, opportunity, contract)


def test_adapter_rejects_contract_hash_drift() -> None:
	contract = _contract()
	opportunity = _opportunity()
	package = _package(opportunity, contract)
	package["data_contract_hash"] = "wrong"
	with pytest.raises(ValueError, match="data contract hash"):
		adapt_factor_research_package(package, opportunity, contract)
