import json
from pathlib import Path

from paper_graph.openalex_snapshot import (
    QUANT_TERMS,
    classify_quant_work,
    extract_arxiv_identity,
    reconstruct_abstract,
)


def test_versioned_config_matches_embedded_retrieval_terms() -> None:
    config = json.loads(
        (Path(__file__).parents[1] / "configs" / "openalex_85_keywords.json").read_text(encoding="utf-8")
    )
    assert config["schema_version"] == "openalex_85_keywords_v1"
    assert len(config["keywords"]) == 85
    assert tuple(config["keywords"]) == QUANT_TERMS


def test_extracts_arxiv_from_location_when_ids_has_only_openalex() -> None:
    work = {
        "ids": {"openalex": "https://openalex.org/W1"},
        "locations": [{
            "id": "pmh:oai:arXiv.org:2601.03260",
            "landing_page_url": "https://arxiv.org/abs/2601.03260",
        }],
    }
    identity = extract_arxiv_identity(work)
    assert identity is not None
    assert identity.arxiv_id == "2601.03260"
    assert identity.method == "locations[0].id"


def test_extracts_versioned_old_style_arxiv_id() -> None:
    work = {"primary_location": {"pdf_url": "https://arxiv.org/pdf/hep-th/9901001v3"}}
    identity = extract_arxiv_identity(work)
    assert identity is not None
    assert identity.arxiv_id == "hep-th/9901001"
    assert identity.version == 3


def test_arxiv_index_flag_without_explicit_id_is_not_identity() -> None:
    assert extract_arxiv_identity({"indexed_in": ["arxiv"]}) is None


def test_reconstructs_abstract_by_position() -> None:
    assert reconstruct_abstract({"finance": [1], "Quantitative": [0], "works": [2]}) == (
        "Quantitative finance works"
    )


def test_reconstructs_parquet_json_abstract() -> None:
    assert reconstruct_abstract('{"flow":[1],"Order":[0]}') == "Order flow"


def test_keyword_aliases_match_hyphen_underscore_and_space() -> None:
    result = classify_quant_work({"title": "Order-flow imbalance and hidden liquidity"})
    assert "order flow imbalance" in result["matched_title_terms"]
    assert "order-flow imbalance" in result["matched_title_terms"]
    assert "hidden_liquidity" in result["matched_title_terms"]


def test_quant_prefilter_preserves_match_reasons() -> None:
    result = classify_quant_work({
        "title": "Realized Volatility Forecasting",
        "keywords": [{"display_name": "Order flow"}],
        "topics": [{"display_name": "Market microstructure"}],
        "abstract_inverted_index": {"transaction": [0], "costs": [1]},
    })
    assert result["is_quant_candidate"] is True
    assert result["quant_score"] == 10
    assert result["matched_title_terms"] == ["realized volatility"]
    assert result["matched_keyword_terms"] == ["order flow", "order-flow"]
    assert result["matched_topic_terms"] == ["microstructure"]
    assert result["matched_abstract_terms"] == ["transaction costs"]