"""Small in-memory storage used by the local API and tests."""

from __future__ import annotations

from collections.abc import Iterable
from difflib import get_close_matches
import json
from pathlib import Path
import re

from .models import PaperEdge


class PaperStore:
    def __init__(self, papers: Iterable[dict] = (), edges: Iterable[PaperEdge] = ()) -> None:
        self.papers = {str(paper["id"]): dict(paper) for paper in papers}
        self.edges = list(edges)

    def search(self, query: str, limit: int = 20) -> list[dict]:
        terms = _expand_query(query)
        if not terms:
            return []
        vocabulary = self._vocabulary()
        ranked: list[tuple[float, dict]] = []
        for paper in self.papers.values():
            fields = {field: _flatten(paper.get(field, "")) for field in ("id", "title", "abstract", "keywords", "authors", "metadata")}
            haystack = " ".join(fields.values())
            score = 0.0
            matched_terms = 0
            author_matches = 0
            for term in terms:
                variants = {term, *_synonyms(term)}
                exact = max((_field_score(variant, fields) for variant in variants), default=0.0)
                if exact == 0.0:
                    correction = get_close_matches(term, vocabulary, n=1, cutoff=0.78)
                    exact = _field_score(correction[0], fields) * 0.82 if correction else 0.0
                if exact > 0:
                    matched_terms += 1
                    score += exact
                    if any(variant in fields["authors"] for variant in variants):
                        author_matches += 1
            # Token overlap gives a small semantic-like boost for related wording.
            query_chars = set("".join(terms))
            overlap = len(query_chars & set(haystack)) / max(len(query_chars), 1)
            if matched_terms == len(terms):
                # Author matches are intentionally boosted so searching a
                # researcher returns more of that researcher's papers rather
                # than only papers whose titles contain the query.
                ranked.append((score + overlap * 0.25 + author_matches * 5.0, paper))
        ranked.sort(key=lambda item: (-item[0], str(item[1].get("title", ""))))
        return [paper for _, paper in ranked[:limit]]

    @staticmethod
    def score(query: str, paper: dict) -> float:
        """Score any provider record with the same fields as local papers."""
        terms = _expand_query(query)
        fields = {field: _flatten(paper.get(field, "")) for field in ("id", "title", "abstract", "keywords", "authors", "metadata")}
        score = 0.0
        for term in terms:
            variants = {term, *_synonyms(term)}
            score += max((_field_score(variant, fields) for variant in variants), default=0.0)
        overlap = len(set("".join(terms)) & set(" ".join(fields.values()))) / max(len(set("".join(terms))), 1)
        author_matches = sum(1 for term in terms if term in fields["authors"])
        return score + overlap * 0.25 + author_matches * 5.0

    def _vocabulary(self) -> set[str]:
        values: set[str] = set()
        for paper in self.papers.values():
            for field in ("id", "title", "abstract", "keywords", "authors", "metadata"):
                values.update(_tokens(_flatten(paper.get(field, ""))))
        return values

    def paper(self, paper_id: str) -> dict | None:
        return self.papers.get(paper_id)

    @classmethod
    def from_jsonl(cls, papers_path: str | Path, edges_path: str | Path) -> "PaperStore":
        """Load the local JSONL demo/processed dataset without network access."""
        with Path(papers_path).open(encoding="utf-8") as handle:
            papers = [json.loads(line) for line in handle if line.strip()]
        with Path(edges_path).open(encoding="utf-8") as handle:
            edges = [PaperEdge(**json.loads(line)) for line in handle if line.strip()]
        return cls(papers, edges)


_SYNONYM_GROUPS = (
    {"波动率", "volatility", "vol", "波动"},
    {"收益率", "return", "returns", "回报", "收益"},
    {"预测", "forecast", "forecasting", "prediction", "predict"},
    {"资产定价", "asset pricing"},
    {"机器学习", "machine learning", "ml"},
    {"深度学习", "deep learning", "neural network", "神经网络"},
    {"风险", "risk"},
)


def _flatten(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values()).casefold()
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten(item) for item in value).casefold()
    return str(value).casefold()


def _tokens(text: str) -> set[str]:
    # Keep both word tokens and CJK runs so Chinese queries work without a tokenizer.
    return set(re.findall(r"[a-z0-9][a-z0-9_-]*|[\u4e00-\u9fff]+", text.casefold()))


def _synonyms(term: str) -> set[str]:
    return {candidate for group in _SYNONYM_GROUPS if term in group for candidate in group if candidate != term}


def _expand_query(query: str) -> list[str]:
    return list(dict.fromkeys(_tokens(query)))


def _field_score(term: str, fields: dict[str, str]) -> float:
    if not term:
        return 0.0
    weights = {"title": 5.0, "keywords": 4.0, "abstract": 3.0, "authors": 6.0, "id": 2.0, "metadata": 1.0}
    return max((weight for field, value in fields.items() if term in value for weight in (weights[field],)), default=0.0)