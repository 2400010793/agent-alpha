from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_parsed_topic_manifest as manifest  # noqa: E402


def test_openalex_match_uses_exact_arxiv_filter(monkeypatch) -> None:
    calls: list[str] = []

    def fake_request(url: str, *, attempts: int = 5):
        calls.append(url)
        return {"results": []}

    monkeypatch.setattr(manifest, "_request_json", fake_request)
    result = manifest.openalex_match({"arxiv_id": "1608.00756", "title": "should not be searched"})

    assert result["status"] == "not_indexed"
    assert result["match_method"] == "arxiv_id"
    assert len(calls) == 1
    assert "filter=ids.arxiv:1608.00756" in calls[0]
    assert "search=" not in calls[0]


def test_openalex_match_returns_exact_match(monkeypatch) -> None:
    monkeypatch.setattr(manifest, "_request_json", lambda url, *, attempts=5: {
        "results": [{
            "id": "https://openalex.org/W123",
            "title": "Exact paper",
            "publication_year": 2020,
            "cited_by_count": 3,
            "referenced_works": ["https://openalex.org/W456"],
        }]
    })

    result = manifest.openalex_match({"arxiv_id": "1608.00756", "title": "Exact paper"})

    assert result["status"] == "matched"
    assert result["match_method"] == "arxiv_id"
    assert result["openalex_id"] == "W123"
    assert result["reference_count"] == 1