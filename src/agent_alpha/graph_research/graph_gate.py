from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Optional

from .ids import NO_EVIDENCE, research_run_id, sha256_content_hash
from .models import GateDecision
from .states import GateStatus


class GraphResearchGate:
	"""Deterministic intake validation for a non-authoritative graph mapping."""

	def __init__(self, completed_run_lookup: Optional[Any] = None) -> None:
		self._completed_run_lookup = completed_run_lookup

	def evaluate(
		self,
		graph: Mapping[str, Any],
		*,
		research_config_hash: Optional[str] = None,
		completed_run_ids: Iterable[str] = (),
	) -> GateDecision:
		if not isinstance(graph, Mapping):
			raise TypeError("graph must be a mapping")

		reasons: set[str] = set()
		missing_papers: set[str] = set()
		missing_evidence: set[str] = set()

		schema_version = self._text(graph.get("schema_version"))
		graph_id = self._text(graph.get("graph_id"))
		graph_version = self._text(graph.get("graph_version"))
		graph_artifact_id = self._text(graph.get("graph_artifact_id"))
		graph_hash = self._text(graph.get("graph_content_hash") or graph.get("content_hash"))
		snapshot_id = self._text(graph.get("snapshot_id") or graph.get("source_snapshot_id") or graph.get("as_of_date"))
		producer_revision = self._text(graph.get("producer_revision"))
		config_hash = self._text(research_config_hash or graph.get("research_config_hash") or graph.get("config_hash"))

		for value, reason in (
			(schema_version, "missing_schema_version"), (graph_id, "missing_graph_id"),
			(graph_version, "missing_graph_version"), (graph_artifact_id, "missing_graph_artifact_id"),
			(graph_hash, "missing_graph_hash"), (snapshot_id, "missing_snapshot_id"),
			(producer_revision, "missing_producer_revision"),
			(config_hash, "missing_research_config_hash"),
		):
			if not value:
				reasons.add(reason)

		seed_ids = self._id_collection(graph.get("seed_paper_ids"), "missing_seed_papers", reasons)
		if not seed_ids:
			reasons.add("missing_seed_papers")

		paper_nodes = graph.get("paper_nodes")
		if not isinstance(paper_nodes, (list, tuple)) or not paper_nodes:
			reasons.add("missing_paper_nodes")
			paper_nodes = ()
		paper_ids: set[str] = set()
		for node in paper_nodes:
			if not isinstance(node, Mapping):
				reasons.add("missing_canonical_paper_id")
				continue
			paper_id = self._text(node.get("canonical_paper_id"))
			if not paper_id:
				reasons.add("missing_canonical_paper_id")
				continue
			paper_ids.add(paper_id)
			identity_method = self._text(node.get("identity_method") or node.get("identity_basis")).lower()
			if node.get("title_only_identity") is True or identity_method in {"title", "title_only", "title-only"}:
				reasons.add("title_only_identity")
			if node.get("unresolved_identity_conflict") is True or node.get("identity_conflict_status") == "unresolved":
				reasons.add("unresolved_identity_conflict")
		if graph.get("unresolved_identity_conflict") is True:
			reasons.add("unresolved_identity_conflict")
		for seed_id in seed_ids:
			if seed_id not in paper_ids:
				missing_papers.add(seed_id)
				reasons.add("seed_paper_outside_graph")

		edges = graph.get("relation_edges")
		single_paper_baseline = graph.get("single_paper_baseline") is True and len(paper_ids) == 1
		if (not isinstance(edges, (list, tuple)) or not edges) and not single_paper_baseline:
			reasons.add("missing_structural_relation")
			edges = ()
		elif not isinstance(edges, (list, tuple)):
			edges = ()
		valid_structural_edge = False
		for edge in edges:
			if not isinstance(edge, Mapping):
				reasons.add("missing_relation_provenance")
				continue
			relation_type = self._text(edge.get("relation_type") or edge.get("type")).upper()
			provenance = edge.get("provenance") or edge.get("provenance_refs") or edge.get("source_artifact")
			if not self._has_value(provenance):
				reasons.add("missing_relation_provenance")
			else:
				valid_structural_edge = True
			if relation_type == "CITES":
				source = self._text(edge.get("source_paper_id") or edge.get("source"))
				target = self._text(edge.get("target_paper_id") or edge.get("target"))
				if not source or not target or edge.get("directed") is False:
					reasons.add("undirected_citation")
			if relation_type == "CONTRADICTS" and not self._valid_contradiction(edge):
				reasons.add("invalid_contradiction_evidence")
		if edges and not valid_structural_edge:
			reasons.add("missing_structural_relation")

		if not self._text(graph.get("research_question")) and not self._text(graph.get("graph_selection_reason")):
			reasons.add("missing_research_question")

		evidence_spans = graph.get("evidence_spans")
		if evidence_spans is None:
			evidence_spans = graph.get("evidence")
		if not isinstance(evidence_spans, (list, tuple)):
			evidence_spans = ()
		valid_evidence = []
		known_evidence_ids: set[str] = set()
		for span in evidence_spans:
			if not isinstance(span, Mapping):
				reasons.add("missing_evidence")
				continue
			evidence_id = self._text(span.get("evidence_id"))
			paper_id = self._text(span.get("canonical_paper_id") or span.get("paper_id"))
			span_hash = self._text(span.get("content_hash"))
			if evidence_id:
				known_evidence_ids.add(evidence_id)
			if not evidence_id or not span_hash:
				reasons.add("missing_evidence")
				if evidence_id:
					missing_evidence.add(evidence_id)
				continue
			if paper_id not in paper_ids:
				reasons.add("evidence_outside_graph")
				if paper_id:
					missing_papers.add(paper_id)
				continue
			valid_evidence.append(span)

		for edge in edges:
			if isinstance(edge, Mapping) and self._text(edge.get("relation_type") or edge.get("type")).upper() == "CONTRADICTS":
				for evidence_id in self._contradiction_evidence_ids(edge):
					if evidence_id not in known_evidence_ids:
						missing_evidence.add(evidence_id)
						reasons.add("invalid_contradiction_evidence")

		fatal_reasons = reasons - {"missing_evidence"}
		if fatal_reasons:
			return self._decision(
				GateStatus.REJECTED, reasons, None, missing_papers, missing_evidence,
				graph_id=graph_id, graph_version=graph_version,
			)

		evidence_hash = self._text(graph.get("evidence_content_hash"))
		if valid_evidence and not evidence_hash:
			evidence_hash = sha256_content_hash(valid_evidence)
		if not valid_evidence:
			evidence_hash = NO_EVIDENCE
		run_id = research_run_id(
			graph_id=graph_id, graph_version=graph_version, graph_artifact_id=graph_artifact_id,
			graph_content_hash=graph_hash, evidence_content_hash=evidence_hash,
			research_config_hash=config_hash, snapshot_id=snapshot_id,
		)
		completed = {str(value).strip() for value in completed_run_ids if str(value).strip()}
		if run_id in completed or self._lookup_completed(run_id):
			return self._decision(
				GateStatus.REJECTED, {"duplicate_completed_run"}, run_id, (), (),
				graph_id=graph_id, graph_version=graph_version,
			)

		structural_only = graph.get("structural_only") is True or graph.get("allow_structural_only") is True
		if not valid_evidence:
			if structural_only:
				return self._decision(
					GateStatus.STRUCTURAL_ONLY, {"structural_only", "missing_evidence"}, run_id,
					paper_ids, (), graph_id=graph_id, graph_version=graph_version,
				)
			return self._decision(
				GateStatus.NEEDS_DIGEST, {"missing_evidence"}, run_id, paper_ids, (),
				graph_id=graph_id, graph_version=graph_version,
			)

		return self._decision(
			GateStatus.ELIGIBLE, {"eligible"}, run_id, (), (),
			graph_id=graph_id, graph_version=graph_version,
		)

	# Compatibility alias kept deliberately small; no orchestration is hidden here.
	check = evaluate

	def _lookup_completed(self, run_id: str) -> bool:
		lookup = self._completed_run_lookup
		if lookup is None:
			return False
		if callable(lookup):
			return bool(lookup(run_id))
		method = getattr(lookup, "is_completed", None)
		if not callable(method):
			raise TypeError("completed_run_lookup must be callable or define is_completed")
		return bool(method(run_id))

	@staticmethod
	def _text(value: Any) -> str:
		return value.strip() if isinstance(value, str) else ""

	@classmethod
	def _id_collection(cls, value: Any, reason: str, reasons: set[str]) -> set[str]:
		if not isinstance(value, (list, tuple, set)) or isinstance(value, (str, bytes)):
			reasons.add(reason)
			return set()
		result = {cls._text(item) for item in value}
		if "" in result:
			reasons.add(reason)
			result.discard("")
		return result

	@staticmethod
	def _has_value(value: Any) -> bool:
		if isinstance(value, str):
			return bool(value.strip())
		if isinstance(value, Mapping):
			return bool(value)
		if isinstance(value, (list, tuple, set)):
			return bool(value)
		return value is not None

	@classmethod
	def _valid_contradiction(cls, edge: Mapping[str, Any]) -> bool:
		left_claim = cls._text(edge.get("source_claim_id") or edge.get("left_claim_id"))
		right_claim = cls._text(edge.get("target_claim_id") or edge.get("right_claim_id"))
		left_evidence = edge.get("source_evidence_ids") or edge.get("left_evidence_ids")
		right_evidence = edge.get("target_evidence_ids") or edge.get("right_evidence_ids")
		return bool(left_claim and right_claim and cls._has_value(left_evidence) and cls._has_value(right_evidence))

	@classmethod
	def _contradiction_evidence_ids(cls, edge: Mapping[str, Any]) -> set[str]:
		result: set[str] = set()
		for name in ("source_evidence_ids", "left_evidence_ids", "target_evidence_ids", "right_evidence_ids"):
			value = edge.get(name)
			if isinstance(value, (list, tuple, set)):
				result.update(cls._text(item) for item in value if cls._text(item))
		return result

	@staticmethod
	def _decision(
		status: GateStatus,
		reasons: Iterable[str],
		run_id: Optional[str],
		missing_papers: Iterable[str],
		missing_evidence: Iterable[str],
		*,
		graph_id: str,
		graph_version: str,
	) -> GateDecision:
		return GateDecision(
			status=status, reason_codes=tuple(reasons),
			details={"graph_id": graph_id, "graph_version": graph_version},
			research_run_id=run_id, missing_paper_ids=tuple(missing_papers),
			missing_evidence_ids=tuple(missing_evidence),
		)


__all__ = ["GraphResearchGate"]
