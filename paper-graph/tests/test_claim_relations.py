import pytest

from paper_graph.claim_relations import ClaimRelationV1, project_verified_relations
from paper_graph.graph import validate_edges


def _relation(**overrides):
    values = {
        "source_paper_id": "arxiv:2401.00001",
        "target_paper_id": "arxiv:2301.00002",
        "source_claim_id": "claim:new-result",
        "target_claim_id": "claim:old-result",
        "relation_type": "SUPPORTS",
        "source_evidence_ids": ["ev:new"],
        "target_evidence_ids": ["ev:old"],
        "scope_alignment": "exact",
        "confidence": 0.9,
        "review_status": "verified",
        "extraction_method": "digest_claim_pair_v1",
        "rationale": "Same estimand, market and horizon with directionally consistent result.",
        "document_versions": {
            "arxiv:2401.00001": "sha256:new",
            "arxiv:2301.00002": "sha256:old",
        },
        "reviewer": "reviewer:test",
    }
    values.update(overrides)
    return ClaimRelationV1.create(**values)


def test_verified_claim_relation_projects_to_valid_graph_edge() -> None:
    relation = _relation()
    edge = relation.to_paper_edge()
    assert edge.relation == "SUPPORTS"
    assert edge.metadata["source_evidence_ids"] == ["ev:new"]
    assert validate_edges([edge]) == []


def test_proposed_relation_is_not_projected() -> None:
    relation = _relation(review_status="proposed", reviewer=None)
    assert project_verified_relations([relation]) == []
    with pytest.raises(ValueError, match="only verified"):
        relation.to_paper_edge()


def test_contradiction_requires_comparable_scope() -> None:
    with pytest.raises(ValueError, match="scope alignment"):
        _relation(relation_type="CONTRADICTS", scope_alignment="incompatible")


def test_projection_keeps_only_relations_inside_graph() -> None:
    relation = _relation()
    assert project_verified_relations([relation], {relation.source_paper_id}) == []
    assert len(project_verified_relations(
        [relation], {relation.source_paper_id, relation.target_paper_id}
    )) == 1
