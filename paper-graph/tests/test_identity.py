from paper_graph.identity import (
    group_exact_identities,
    normalize_doi,
    normalize_openalex_id,
    resolve_identity,
)


def test_normalizes_provider_identifiers() -> None:
    assert normalize_doi("https://doi.org/10.1000/ABC.1") == "10.1000/abc.1"
    assert normalize_doi("doi:10.48550/arXiv.2601.03260") == "10.48550/arxiv.2601.03260"
    assert normalize_openalex_id("https://openalex.org/W123") == "W123"
    assert normalize_openalex_id("openalex:w456") == "W456"


def test_resolve_identity_prefers_exact_arxiv_over_doi() -> None:
    identity = resolve_identity({
        "id": "https://openalex.org/W1",
        "doi": "https://doi.org/10.1000/example",
        "locations": [{"id": "pmh:oai:arXiv.org:2601.03260"}],
    })
    assert identity.canonical_paper_id == "arxiv:2601.03260"
    assert identity.openalex_id == "W1"
    assert identity.doi == "10.1000/example"


def test_exact_doi_groups_records_but_title_does_not() -> None:
    groups = group_exact_identities([
        {"id": "https://openalex.org/W1", "title": "Same", "doi": "10.1000/ONE"},
        {"id": "https://openalex.org/W2", "title": "Different", "doi": "https://doi.org/10.1000/one"},
        {"id": "https://openalex.org/W3", "title": "Same"},
    ])
    assert sorted(group["member_count"] for group in groups) == [1, 2]
    merged = next(group for group in groups if group["member_count"] == 2)
    assert merged["member_openalex_ids"] == ["W1", "W2"]
    assert merged["merge_methods"] == ["doi"]


def test_transitive_arxiv_and_doi_evidence_forms_one_group() -> None:
    groups = group_exact_identities([
        {"openalex_id": "W1", "arxiv_id": "2601.03260", "doi": "10.1000/a"},
        {"openalex_id": "W2", "doi": "10.1000/a"},
        {"openalex_id": "W3", "arxiv_id": "2601.03260"},
    ])
    assert len(groups) == 1
    assert groups[0]["member_count"] == 3
    assert groups[0]["merge_methods"] == ["arxiv", "doi"]