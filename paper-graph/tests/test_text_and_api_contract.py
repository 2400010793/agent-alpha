from paper_graph.embeddings import HashEmbeddingEncoder
from paper_graph.text import build_embedding_text


def test_primary_embedding_prefers_title_and_keywords() -> None:
    text, quality = build_embedding_text({"title": "Factor Models", "keywords": ["asset pricing", "Asset Pricing"]})
    assert text == "Title: Factor Models\nKeywords: asset pricing"
    assert quality == "A"


def test_hash_embedding_is_deterministic() -> None:
    encoder = HashEmbeddingEncoder(16)
    assert encoder.encode("Title: Factor Models") == encoder.encode("Title: Factor Models")