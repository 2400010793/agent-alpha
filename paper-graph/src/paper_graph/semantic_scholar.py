"""Small Semantic Scholar client used for Connected Papers-style expansion."""

from __future__ import annotations

import json
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from typing import Any


class SemanticScholarClient:
    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout
        self.base = "https://api.semanticscholar.org"
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.cache_ttl = 120.0

    def _get(self, path: str) -> dict[str, Any]:
        cached = self._cache.get(path)
        if cached and time.monotonic() - cached[0] < self.cache_ttl:
            return cached[1]
        request = Request(self.base + path, headers={"User-Agent": "paper-graph/0.1"})
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.load(response)
        self._cache[path] = (time.monotonic(), payload)
        return payload

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        cache_key = f"POST {path} {json.dumps(body, sort_keys=True)}"
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < self.cache_ttl:
            return cached[1]
        request = Request(
            self.base + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"User-Agent": "paper-graph/0.1", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.load(response)
        self._cache[cache_key] = (time.monotonic(), payload)
        return payload

    @staticmethod
    def _provider_id(paper_id: str) -> str:
        """Translate local canonical IDs to Semantic Scholar lookup IDs."""
        if paper_id.lower().startswith("arxiv:"):
            return f"ARXIV:{paper_id.split(':', 1)[1]}"
        if paper_id.lower().startswith("doi:"):
            return paper_id.split(":", 1)[1]
        if paper_id.lower().startswith("s2:"):
            return paper_id.split(":", 1)[1]
        return paper_id

    @staticmethod
    def _paper(item: dict[str, Any]) -> dict[str, Any]:
        external = item.get("externalIds") or {}
        arxiv = external.get("ArXiv") or external.get("ARXIV")
        paper_id = str(item.get("paperId") or (f"arxiv:{arxiv}" if arxiv else external.get("DOI") or ""))
        authors = [author for author in item.get("authors", []) if author.get("name")]
        return {
            "id": paper_id,
            "title": item.get("title") or "Untitled paper",
            "authors": [author.get("name", "") for author in authors],
            "year": item.get("year"),
            "citation_count": int(item.get("citationCount") or 0),
            "global_impact": float(item.get("citationCount") or 0),
            "abstract": item.get("abstract") or "",
            "url": (f"https://arxiv.org/abs/{arxiv}" if arxiv else f"https://www.semanticscholar.org/paper/{paper_id}"),
            "keywords": [],
            "metadata": {
                "provider": "semantic_scholar",
                "external_ids": external,
                # Keep provider IDs so shared-author edges do not equate two
                # different researchers who happen to have the same name.
                "author_ids": [str(author["authorId"]) for author in authors if author.get("authorId")],
            },
        }

    def search(self, query: str, limit: int = 40) -> list[dict[str, Any]]:
        fields = "paperId,title,year,authors,externalIds,abstract,citationCount"
        payload = self._get(f"/graph/v1/paper/search?query={quote(query)}&limit={min(limit, 100)}&fields={fields}")
        return [self._paper(item) for item in payload.get("data", [])]

    def search_authors(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        payload = self._get(f"/graph/v1/author/search?query={quote(query)}&limit={min(limit, 100)}")
        return [{"id": str(item.get("authorId")), "name": item.get("name") or "Unknown author", "paper_count": item.get("paperCount"), "citation_count": item.get("citationCount")} for item in payload.get("data", []) if item.get("authorId")]

    def author_papers(self, author_id: str, limit: int = 40, offset: int = 0) -> list[dict[str, Any]]:
        fields = "paperId,title,year,authors,externalIds,abstract,citationCount"
        payload = self._get(f"/graph/v1/author/{quote(author_id, safe='')}/papers?limit={min(limit, 100)}&offset={max(offset, 0)}&fields={fields}")
        return [self._paper(item) for item in payload.get("data", [])]

    def paper(self, paper_id: str) -> dict[str, Any]:
        fields = "paperId,title,year,authors,externalIds,abstract,citationCount,references.paperId,citations.paperId"
        provider_id = self._provider_id(paper_id)
        raw = self._get(f"/graph/v1/paper/{quote(provider_id, safe='')}?fields={fields}")
        paper = self._paper(raw)
        paper["metadata"]["references"] = [item.get("paperId") for item in raw.get("references", []) if item.get("paperId")]
        paper["metadata"]["cited_by"] = [item.get("paperId") for item in raw.get("citations", []) if item.get("paperId")]
        return paper

    def _list_relation(self, paper_id: str, relation: str, limit: int) -> list[dict[str, Any]]:
        fields = "paperId,title,year,authors,externalIds,abstract,citationCount"
        payload = self._get(
            f"/graph/v1/paper/{quote(paper_id, safe='')}/{relation}?limit={min(limit, 100)}&fields={fields}"
        )
        key = "citedPaper" if relation == "references" else "citingPaper"
        return [self._paper(item[key]) for item in payload.get("data", []) if item.get(key)]

    def expand(self, paper_id: str, limit: int = 40) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Return a seed and its Connected Papers-style discovery candidates.

        References and citations provide the structural neighborhood; the
        recommendations endpoint adds papers that are close in the provider's
        literature graph. The caller scores the merged candidate set locally.
        """
        seed = self.paper(paper_id)
        candidates: dict[str, dict[str, Any]] = {}
        for relation in ("references", "citations"):
            for paper in self._list_relation(paper_id, relation, limit):
                paper["metadata"]["discovered_via"] = relation
                paper["metadata"]["discovered_from"] = paper_id
                candidates[paper["id"]] = paper
        for paper in self.related(paper_id, limit):
            paper["metadata"]["discovered_via"] = "related"
            paper["metadata"]["discovered_from"] = paper_id
            candidates[paper["id"]] = paper
        candidates.pop(seed["id"], None)
        # Fetch bounded relation sets for candidate papers so the graph can
        # calculate co-citation/bibliographic coupling instead of treating
        # provider recommendations as citation edges.
        for candidate_id in list(candidates)[:limit]:
            try:
                enriched = self.paper(candidate_id)
                enriched["metadata"]["discovered_via"] = candidates[candidate_id]["metadata"].get("discovered_via")
                candidates[candidate_id] = enriched
            except Exception:
                continue
        return seed, list(candidates.values())[: max(0, limit - 1)]

    def related(self, paper_id: str, limit: int = 40) -> list[dict[str, Any]]:
        fields = "paperId,title,year,authors,externalIds,abstract,citationCount"
        payload = self._get(f"/recommendations/v1/papers/forpaper/{quote(paper_id, safe='')[:100]}?limit={min(limit, 100)}&fields={fields}")
        return [self._paper(item) for item in payload.get("recommendedPapers", [])]

    def recommendations(self, paper_ids: list[str], limit: int = 40) -> list[dict[str, Any]]:
        """Return semantic recommendations for one or more positive seeds."""
        positive = [self._provider_id(value) for value in paper_ids if value]
        if not positive:
            return []
        payload = self._post(
            "/recommendations/v1/papers/",
            {"positivePaperIds": positive, "negativePaperIds": [], "limit": min(limit, 100)},
        )
        return [self._paper(item) for item in payload.get("recommendedPapers", [])]
