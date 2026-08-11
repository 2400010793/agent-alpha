from __future__ import annotations

from copy import deepcopy

import pytest

from agent_alpha.graph_research.graph_gate import GraphResearchGate
from agent_alpha.graph_research.states import GateStatus


def _graph(*, evidence: bool = True, structural_only: bool = False) -> dict:
	graph = {
		"schema_version": "paper_graph_research_input_v0_test_only",
		"graph_id": "graph_1", "graph_version": "v1", "graph_artifact_id": "artifact_1",
		"content_hash": "graph_hash", "snapshot_id": "snapshot_1", "config_hash": "config_hash",
		"producer_revision": "paper_graph_rev_1",
		"seed_paper_ids": ["paper_1"],
		"paper_nodes": [
			{"canonical_paper_id": "paper_1", "identity_method": "exact_arxiv"},
			{"canonical_paper_id": "paper_2", "identity_method": "exact_doi"},
		],
		"relation_edges": [{
			"relation_type": "CITES", "source_paper_id": "paper_1", "target_paper_id": "paper_2",
			"directed": True, "provenance": {"source": "openalex_snapshot"},
		}],
		"research_question": "Does the linked mechanism replicate?",
		"structural_only": structural_only,
	}
	if evidence:
		graph["evidence_spans"] = [
			{"evidence_id": "evidence_1", "canonical_paper_id": "paper_1", "content_hash": "hash_1"},
		]
	return graph


def test_gate_returns_all_four_decisions() -> None:
	gate = GraphResearchGate()
	eligible = gate.evaluate(_graph())
	assert eligible.status == GateStatus.ELIGIBLE and eligible.research_run_id.startswith("grun_")
	structural = gate.evaluate(_graph(evidence=False, structural_only=True))
	assert structural.status == GateStatus.STRUCTURAL_ONLY
	needs_digest = gate.evaluate(_graph(evidence=False))
	assert needs_digest.status == GateStatus.NEEDS_DIGEST
	assert needs_digest.missing_paper_ids == ("paper_1", "paper_2")
	assert gate.evaluate({}).status == GateStatus.REJECTED


def test_explicit_single_paper_baseline_does_not_require_a_relation_edge() -> None:
	graph = _graph()
	graph["paper_nodes"] = graph["paper_nodes"][:1]
	graph["relation_edges"] = []
	graph["single_paper_baseline"] = True
	decision = GraphResearchGate().evaluate(graph)
	assert decision.status == GateStatus.ELIGIBLE


def test_multi_paper_graph_cannot_bypass_relation_requirement() -> None:
	graph = _graph()
	graph["relation_edges"] = []
	graph["single_paper_baseline"] = True
	decision = GraphResearchGate().evaluate(graph)
	assert decision.status == GateStatus.REJECTED
	assert "missing_structural_relation" in decision.reason_codes


@pytest.mark.parametrize(
	"mutate,reason",
	[
		(lambda graph: graph["paper_nodes"][0].update(identity_method="title_only"), "title_only_identity"),
		(lambda graph: graph["paper_nodes"][0].update(unresolved_identity_conflict=True), "unresolved_identity_conflict"),
		(lambda graph: graph["relation_edges"][0].pop("provenance"), "missing_relation_provenance"),
		(lambda graph: graph["evidence_spans"][0].update(canonical_paper_id="paper_outside"), "evidence_outside_graph"),
	],
)
def test_gate_rejects_invalid_identity_relation_and_evidence(mutate, reason: str) -> None:
	graph = _graph()
	mutate(graph)
	decision = GraphResearchGate().evaluate(graph)
	assert decision.status == GateStatus.REJECTED
	assert reason in decision.reason_codes


def test_contradiction_requires_both_claims_and_both_evidence_sides() -> None:
	graph = _graph()
	graph["relation_edges"].append({
		"relation_type": "CONTRADICTS", "source_claim_id": "claim_1", "target_claim_id": "claim_2",
		"source_evidence_ids": ["evidence_1"], "provenance": {"source": "digest"},
	})
	decision = GraphResearchGate().evaluate(graph)
	assert decision.status == GateStatus.REJECTED
	assert "invalid_contradiction_evidence" in decision.reason_codes


def test_duplicate_completed_run_is_rejected() -> None:
	first = GraphResearchGate().evaluate(_graph())
	decision = GraphResearchGate(lambda run_id: run_id == first.research_run_id).evaluate(_graph())
	assert decision.status == GateStatus.REJECTED
	assert decision.reason_codes == ("duplicate_completed_run",)
	assert decision.research_run_id == first.research_run_id
