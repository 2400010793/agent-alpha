"""Build immutable graph-conditioned research opportunities and intake packages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from .claim_relations import ClaimRelationV1
from .graph_value import GraphValueAssessmentV1
from .research_contracts import canonical_hash


OPPORTUNITY_STATUSES = frozenset({
    "READY",
    "EVIDENCE_QUEUE",
    "NEEDS_DATA",
    "METHOD_REVIEW",
    "HUMAN_REVIEW",
})


def _ids(values: Iterable[Any], name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    result = tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    if not result and not allow_empty:
        raise ValueError(f"{name} must contain at least one stable ID")
    return result


def _opportunity_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "as_of_date": value["as_of_date"],
        "graph_id": value["graph_id"],
        "graph_version": value["graph_version"],
        "graph_content_hash": value["graph_content_hash"],
        "taxonomy_version": value["taxonomy_version"],
        "topic_ids": list(value["topic_ids"]),
        "seed_paper_ids": list(value["seed_paper_ids"]),
        "neighbor_paper_ids": list(value["neighbor_paper_ids"]),
        "relation_refs": list(value["relation_refs"]),
        "evolution_path_refs": list(value["evolution_path_refs"]),
        "structured_artifact_refs": list(value["structured_artifact_refs"]),
        "research_question": value["research_question"],
        "target_tracks": list(value["target_tracks"]),
        "required_observables": list(value["required_observables"]),
        "graph_value_assessment_id": value["graph_value_assessment_id"],
        "config_hash": value["config_hash"],
    }


def _package_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "research_opportunity_id": value["research_opportunity_id"],
        "research_opportunity_hash": value["research_opportunity_hash"],
        "graph_snapshot_ref": dict(value["graph_snapshot_ref"]),
        "paper_artifact_refs": list(value["paper_artifact_refs"]),
        "evidence_bundle_hash": value["evidence_bundle_hash"],
        "target_track": value["target_track"],
        "data_contract_id": value["data_contract_id"],
        "data_contract_hash": value["data_contract_hash"],
        "field_registry_version": value["field_registry_version"],
        "operator_registry_version": value["operator_registry_version"],
        "memory_snapshot_id": value["memory_snapshot_id"],
        "research_budget": dict(value["research_budget"]),
    }


@dataclass(frozen=True)
class StructuredPaperArtifactRefV1:
    """Minimal adapter consumed from the separately-owned paper structurer."""

    artifact_id: str
    paper_id: str
    document_version: str
    content_hash: str
    claim_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    contribution_types: tuple[str, ...] = ()
    schema_version: str = "structured_paper_artifact_ref_v1"

    def __post_init__(self) -> None:
        for name in ("artifact_id", "paper_id", "document_version", "content_hash"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must be non-empty")
        if self.schema_version != "structured_paper_artifact_ref_v1":
            raise ValueError("unsupported structured paper artifact ref schema_version")
        object.__setattr__(self, "claim_ids", _ids(self.claim_ids, "claim_ids", allow_empty=True))
        object.__setattr__(self, "evidence_ids", _ids(self.evidence_ids, "evidence_ids", allow_empty=True))
        object.__setattr__(self, "contribution_types", _ids(
            self.contribution_types, "contribution_types", allow_empty=True
        ))

    @property
    def evidence_ready(self) -> bool:
        return bool(self.claim_ids and self.evidence_ids)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StructuredPaperArtifactRefV1":
        payload = dict(value)
        for name in ("claim_ids", "evidence_ids", "contribution_types"):
            payload[name] = tuple(payload.get(name) or ())
        return cls(**payload)


@dataclass(frozen=True)
class ResearchOpportunityV1:
    research_opportunity_id: str
    as_of_date: str
    graph_id: str
    graph_version: str
    graph_content_hash: str
    taxonomy_version: str
    topic_ids: tuple[str, ...]
    seed_paper_ids: tuple[str, ...]
    neighbor_paper_ids: tuple[str, ...]
    relation_refs: tuple[Mapping[str, Any], ...]
    evolution_path_refs: tuple[Mapping[str, Any], ...]
    structured_artifact_refs: tuple[Mapping[str, Any], ...]
    contribution_type_mix: tuple[str, ...]
    research_question: str
    selection_reasons: tuple[str, ...]
    target_tracks: tuple[str, ...]
    required_observables: tuple[str, ...]
    digest_ready_paper_ids: tuple[str, ...]
    missing_evidence_paper_ids: tuple[str, ...]
    prior_art_search_trace: Mapping[str, Any]
    graph_value_assessment_id: str
    recommended_action: str
    status: str
    producer_revision: str
    config_hash: str
    schema_version: str = "research_opportunity_v1"

    def __post_init__(self) -> None:
        for name in (
            "research_opportunity_id", "as_of_date", "graph_id", "graph_version",
            "graph_content_hash", "taxonomy_version", "research_question",
            "graph_value_assessment_id", "recommended_action", "status",
            "producer_revision", "config_hash",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must be non-empty")
        if self.schema_version != "research_opportunity_v1":
            raise ValueError("unsupported research opportunity schema_version")
        if self.status not in OPPORTUNITY_STATUSES:
            raise ValueError(f"unsupported research opportunity status: {self.status}")
        if set(self.seed_paper_ids) & set(self.neighbor_paper_ids):
            raise ValueError("seed and neighbor paper IDs must be disjoint")
        if not set(self.digest_ready_paper_ids).issubset(
            set(self.seed_paper_ids) | set(self.neighbor_paper_ids)
        ):
            raise ValueError("digest-ready papers must belong to the graph opportunity")
        if not set(self.missing_evidence_paper_ids).issubset(
            set(self.seed_paper_ids) | set(self.neighbor_paper_ids)
        ):
            raise ValueError("missing-evidence papers must belong to the graph opportunity")
        expected = "opportunity:" + canonical_hash(self.identity_payload())[:24]
        if self.research_opportunity_id != expected:
            raise ValueError("research_opportunity_id does not match immutable inputs")

    def identity_payload(self) -> dict[str, Any]:
        return _opportunity_identity(self.__dict__)

    @classmethod
    def create(cls, **values: Any) -> "ResearchOpportunityV1":
        payload = dict(values)
        for name in (
            "topic_ids", "seed_paper_ids", "neighbor_paper_ids", "contribution_type_mix",
            "selection_reasons", "target_tracks", "required_observables",
            "digest_ready_paper_ids", "missing_evidence_paper_ids",
        ):
            payload[name] = tuple(payload.get(name) or ())
        for name in ("relation_refs", "evolution_path_refs", "structured_artifact_refs"):
            payload[name] = tuple(payload.get(name) or ())
        payload["research_opportunity_id"] = "opportunity:" + canonical_hash(
            _opportunity_identity(payload)
        )[:24]
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for name in (
            "topic_ids", "seed_paper_ids", "neighbor_paper_ids", "relation_refs",
            "evolution_path_refs", "structured_artifact_refs", "contribution_type_mix",
            "selection_reasons", "target_tracks", "required_observables",
            "digest_ready_paper_ids", "missing_evidence_paper_ids",
        ):
            value[name] = list(value[name])
        return value


@dataclass(frozen=True)
class FactorResearchPackageV1:
    package_id: str
    research_opportunity_id: str
    research_opportunity_hash: str
    graph_snapshot_ref: Mapping[str, Any]
    paper_artifact_refs: tuple[Mapping[str, Any], ...]
    evidence_bundle_hash: str
    target_track: str
    data_contract_id: str
    data_contract_hash: str
    field_registry_version: str
    operator_registry_version: str
    memory_snapshot_id: str
    research_budget: Mapping[str, Any]
    selection_trace: Mapping[str, Any]
    schema_version: str = "factor_research_package_v1"

    def __post_init__(self) -> None:
        for name in (
            "package_id", "research_opportunity_id", "research_opportunity_hash",
            "evidence_bundle_hash", "target_track", "data_contract_id",
            "data_contract_hash", "field_registry_version", "operator_registry_version",
            "memory_snapshot_id",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must be non-empty")
        if self.schema_version != "factor_research_package_v1":
            raise ValueError("unsupported factor research package schema_version")
        expected = "researchpkg:" + canonical_hash(self.identity_payload())[:24]
        if self.package_id != expected:
            raise ValueError("package_id does not match immutable package inputs")

    def identity_payload(self) -> dict[str, Any]:
        return _package_identity(self.__dict__)

    @classmethod
    def create(cls, **values: Any) -> "FactorResearchPackageV1":
        payload = dict(values)
        payload["paper_artifact_refs"] = tuple(payload.get("paper_artifact_refs") or ())
        payload["package_id"] = "researchpkg:" + canonical_hash(_package_identity(payload))[:24]
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["paper_artifact_refs"] = list(self.paper_artifact_refs)
        return value


def build_research_opportunity(
    graph: Mapping[str, Any],
    artifacts: Iterable[StructuredPaperArtifactRefV1],
    relations: Iterable[ClaimRelationV1],
    assessment: GraphValueAssessmentV1,
    *,
    as_of_date: str,
    taxonomy_version: str,
    research_question: str,
    required_observables: Iterable[str],
    producer_revision: str,
    config_hash: str,
    prior_art_search_trace: Mapping[str, Any] | None = None,
    evolution_path_refs: Iterable[Mapping[str, Any]] = (),
) -> ResearchOpportunityV1:
    """Construct one opportunity without inventing missing paper evidence."""

    graph_id = str(graph.get("graph_id") or graph.get("category") or "").strip()
    if not graph_id:
        raise ValueError("graph requires graph_id or category")
    graph_version = str(graph.get("schema_version") or "unversioned")
    graph_hash = canonical_hash(graph)
    nodes = [node for node in graph.get("nodes", []) if node.get("id")]
    node_ids = tuple(str(node["id"]) for node in nodes)
    explicit_seeds = {str(value) for value in graph.get("seed_ids", [])}
    seed_ids = tuple(
        paper_id for paper_id, node in zip(node_ids, nodes)
        if paper_id in explicit_seeds or node.get("is_seed")
    )
    if not seed_ids and node_ids:
        seed_ids = (node_ids[0],)
    neighbor_ids = tuple(paper_id for paper_id in node_ids if paper_id not in set(seed_ids))
    artifact_by_paper = {
        artifact.paper_id: artifact for artifact in artifacts if artifact.paper_id in set(node_ids)
    }
    ready_ids = tuple(
        paper_id for paper_id in node_ids
        if paper_id in artifact_by_paper and artifact_by_paper[paper_id].evidence_ready
    )
    missing_ids = tuple(paper_id for paper_id in node_ids if paper_id not in set(ready_ids))
    relation_refs = []
    for relation in relations:
        if (
            relation.review_status == "verified"
            and relation.source_paper_id in set(node_ids)
            and relation.target_paper_id in set(node_ids)
        ):
            relation_refs.append({
                "relation_id": relation.relation_id,
                "relation_type": relation.relation_type,
                "source_paper_id": relation.source_paper_id,
                "target_paper_id": relation.target_paper_id,
                "source_claim_id": relation.source_claim_id,
                "target_claim_id": relation.target_claim_id,
                "source_evidence_ids": list(relation.source_evidence_ids),
                "target_evidence_ids": list(relation.target_evidence_ids),
                "scope_alignment": relation.scope_alignment,
                "confidence": relation.confidence,
                "review_status": relation.review_status,
            })
    artifact_refs = tuple({
        "artifact_id": artifact.artifact_id,
        "paper_id": artifact.paper_id,
        "document_version": artifact.document_version,
        "content_hash": artifact.content_hash,
        "claim_ids": list(artifact.claim_ids),
        "evidence_ids": list(artifact.evidence_ids),
    } for artifact in artifact_by_paper.values())
    contribution_types = tuple(sorted({
        value for artifact in artifact_by_paper.values()
        for value in artifact.contribution_types
    }))
    topic_id = str(graph.get("topic_id") or graph.get("category") or "").strip()
    topic_ids = (topic_id,) if topic_id else tuple(sorted({
        str((node.get("metadata") or {}).get("topic_id") or "") for node in nodes
        if (node.get("metadata") or {}).get("topic_id")
    }))
    seed_evidence_ready = set(seed_ids).issubset(set(ready_ids))
    has_verified_disagreement = any(
        value["relation_type"] in {"CONTRADICTS", "FAILS_TO_REPLICATE"}
        for value in relation_refs
    )
    if (
        assessment.recommended_action == "BUILD_EVIDENCE"
        or not seed_evidence_ready
        or (
            assessment.recommended_action == "RESOLVE_CONTRADICTION"
            and not has_verified_disagreement
        )
    ):
        status = "EVIDENCE_QUEUE"
    elif assessment.recommended_action == "NEEDS_DATA":
        status = "NEEDS_DATA"
    elif assessment.recommended_action == "REVIEW_RESEARCH_OPPORTUNITY":
        status = "HUMAN_REVIEW"
    elif assessment.recommended_action == "RUN_FEATURE_OR_METHOD_RESEARCH":
        status = "METHOD_REVIEW"
    else:
        status = "READY"
    return ResearchOpportunityV1.create(
        as_of_date=as_of_date,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_content_hash=graph_hash,
        taxonomy_version=taxonomy_version,
        topic_ids=topic_ids,
        seed_paper_ids=seed_ids,
        neighbor_paper_ids=neighbor_ids,
        relation_refs=relation_refs,
        evolution_path_refs=tuple(evolution_path_refs),
        structured_artifact_refs=artifact_refs,
        contribution_type_mix=contribution_types,
        research_question=research_question,
        selection_reasons=assessment.reasons,
        target_tracks=(assessment.target_track,),
        required_observables=tuple(required_observables),
        digest_ready_paper_ids=ready_ids,
        missing_evidence_paper_ids=missing_ids,
        prior_art_search_trace=dict(prior_art_search_trace or {}),
        graph_value_assessment_id=assessment.assessment_id,
        recommended_action=assessment.recommended_action,
        status=status,
        producer_revision=producer_revision,
        config_hash=config_hash,
    )


def build_factor_research_package(
    opportunity: ResearchOpportunityV1,
    *,
    target_track: str,
    data_contract_id: str,
    data_contract_hash: str,
    field_registry_version: str,
    operator_registry_version: str,
    memory_snapshot_id: str,
    research_budget: Mapping[str, Any],
    selection_trace: Mapping[str, Any],
) -> FactorResearchPackageV1:
    if opportunity.status != "READY":
        raise ValueError(f"only READY opportunities may become research packages: {opportunity.status}")
    if target_track not in opportunity.target_tracks:
        raise ValueError("target_track is not authorized by the research opportunity")
    opportunity_payload = opportunity.to_dict()
    return FactorResearchPackageV1.create(
        research_opportunity_id=opportunity.research_opportunity_id,
        research_opportunity_hash=canonical_hash(opportunity_payload),
        graph_snapshot_ref={
            "graph_id": opportunity.graph_id,
            "graph_version": opportunity.graph_version,
            "graph_content_hash": opportunity.graph_content_hash,
        },
        paper_artifact_refs=opportunity.structured_artifact_refs,
        evidence_bundle_hash=canonical_hash({
            "artifacts": list(opportunity.structured_artifact_refs),
            "relations": list(opportunity.relation_refs),
        }),
        target_track=target_track,
        data_contract_id=data_contract_id,
        data_contract_hash=data_contract_hash,
        field_registry_version=field_registry_version,
        operator_registry_version=operator_registry_version,
        memory_snapshot_id=memory_snapshot_id,
        research_budget=dict(research_budget),
        selection_trace=dict(selection_trace),
    )


__all__ = [
    "FactorResearchPackageV1",
    "OPPORTUNITY_STATUSES",
    "ResearchOpportunityV1",
    "StructuredPaperArtifactRefV1",
    "build_factor_research_package",
    "build_research_opportunity",
]
