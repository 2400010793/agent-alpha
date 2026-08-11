from pathlib import Path

import duckdb

from paper_graph.openalex_extraction import (
    canonical_hash,
    checkpoint_matches,
    project_products,
    write_partitioned_products,
)


def _row(*, graph_seed: bool = True, digest_seed: bool = False) -> dict:
    return {
        "canonical_paper_id": "arxiv:2401.00001",
        "openalex_id": "W1",
        "title": "Order Flow in Limit Order Books",
        "authors": [{"name": "A"}],
        "publication_year": 2024,
        "publication_date": "2024-01-01",
        "doi": None,
        "arxiv_id": "2401.00001",
        "arxiv_version": None,
        "identity_method": "locations[0].id",
        "identity_evidence": "pmh:oai:arXiv.org:2401.00001",
        "identity_confidence": "exact",
        "topics": [],
        "keywords": [],
        "concepts": [],
        "referenced_works": ["W2"],
        "referenced_works_count": 1,
        "cited_by_count": 2,
        "quant_match": {"matched_title_terms": ["order flow"]},
        "finance_status": "accepted",
        "finance_audit_version": "finance_audit_v3",
        "finance_audit_reasons": ["strong_finance_anchor:order flow"],
        "finance_anchors": ["order flow"],
        "graph_seed_eligible": graph_seed,
        "digest_seed_eligible": digest_seed,
        "snapshot_date": "2026-06-26",
        "selection_version": "openalex_85_keyword_v1",
    }


def test_product_projection_keeps_layers_separate() -> None:
    products = project_products([_row(graph_seed=True, digest_seed=False)])
    assert len(products["retrieval"]) == 1
    assert len(products["audit"]) == 1
    assert len(products["identity"]) == 1
    assert len(products["graph_seed"]) == 1
    assert products["digest_seed"] == []
    assert "finance_status" not in products["retrieval"][0]
    assert products["audit"][0]["finance_status"] == "accepted"
    assert "research_value_tier" in products["audit"][0]


def test_partitioned_parquet_is_atomic_and_queryable(tmp_path: Path) -> None:
    connection = duckdb.connect()
    outputs = write_partitioned_products(
        connection,
        [_row(graph_seed=True, digest_seed=False)],
        output_root=tmp_path,
        source_relative_path=Path("updated_date=2026-06-26/part_0001.parquet"),
    )
    retrieval = next(item for item in outputs if item["product"] == "retrieval")
    assert retrieval["row_count"] == 1
    assert retrieval["sha256"]
    parquet_path = Path(retrieval["path"])
    assert parquet_path.exists()
    assert not list(parquet_path.parent.glob("*.tmp-*"))
    assert connection.execute("SELECT openalex_id FROM read_parquet(?)", [str(parquet_path)]).fetchone() == ("W1",)
    digest = next(item for item in outputs if item["product"] == "digest_seed")
    assert digest["path"] is None
    assert digest["row_count"] == 0


def test_checkpoint_requires_matching_source_config_and_output_hash(tmp_path: Path) -> None:
    output = tmp_path / "part.parquet"
    output.write_bytes(b"parquet")
    source = {"relative_path": "part.parquet", "content_length": 10, "sha256": "a" * 64}
    config_hash = canonical_hash({"version": 1})
    import hashlib

    record = {
        "source": source,
        "config_hash": config_hash,
        "outputs": [{
            "path": str(output),
            "row_count": 1,
            "content_length": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        }],
    }
    assert checkpoint_matches(record, source=source, config_hash=config_hash)
    output.write_bytes(b"changed")
    assert not checkpoint_matches(record, source=source, config_hash=config_hash)
