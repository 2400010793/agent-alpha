"""Small, key-free clients for Crossref and OpenAlex metadata search."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote
from urllib.request import Request, urlopen
from typing import Any

from .openalex_snapshot import extract_arxiv_identity


class OpenAcademicClient:
    def __init__(self, timeout: float = 12.0) -> None:
        self.timeout = timeout

    def _get(self, url: str) -> dict[str, Any]:
        request = Request(url, headers={"User-Agent": "paper-graph/0.1 (mailto:paper-graph@example.org)"})
        with urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    @staticmethod
    def _authors(items: list[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for item in items:
            name = item.get("name") or " ".join(filter(None, [item.get("given"), item.get("family")]))
            if name:
                names.append(str(name))
        return names

    @staticmethod
    def _paper(*, paper_id: str, title: str, authors: list[str], year: int | None,
               abstract: str = "", doi: str | None = None, url: str = "",
               provider: str) -> dict[str, Any]:
        return {
            "id": paper_id,
            "title": title or "Untitled paper",
            "authors": authors,
            "year": year,
            "citation_count": 0,
            "global_impact": 0.0,
            "abstract": abstract,
            "url": url,
            "keywords": [],
            "metadata": {"provider": provider, "doi": doi, "external_ids": {"DOI": doi} if doi else {}},
        }

    def crossref_search(self, query: str, limit: int = 40) -> list[dict[str, Any]]:
        payload = self._get(f"https://api.crossref.org/works?query.bibliographic={quote(query)}&rows={min(limit, 100)}")
        results: list[dict[str, Any]] = []
        for item in payload.get("message", {}).get("items", []):
            doi = item.get("DOI")
            if not doi:
                continue
            date = item.get("published-print") or item.get("published-online") or item.get("issued") or {}
            parts = date.get("date-parts", [[]])
            year = parts[0][0] if parts and parts[0] else None
            results.append(self._paper(
                paper_id=f"doi:{doi}", title="; ".join(item.get("title", [])),
                authors=self._authors(item.get("author", [])), year=year,
                doi=doi, url=item.get("URL") or f"https://doi.org/{doi}", provider="crossref",
            ))
        return results

    def openalex_search(self, query: str, limit: int = 40) -> list[dict[str, Any]]:
        payload = self._get(f"https://api.openalex.org/works?search={quote(query)}&per-page={min(limit, 100)}")
        results: list[dict[str, Any]] = []
        for item in payload.get("results", []):
            openalex_id = str(item.get("id") or "")
            if not openalex_id:
                continue
            doi = item.get("doi")
            authors = [((author.get("author") or {}).get("display_name") or "") for author in item.get("authorships", [])]
            results.append(self._paper(
                paper_id=f"openalex:{openalex_id.rsplit('/', 1)[-1]}", title=item.get("title") or "",
                authors=[name for name in authors if name], year=item.get("publication_year"),
                doi=doi.replace("https://doi.org/", "") if isinstance(doi, str) else None,
                url=item.get("doi") or item.get("primary_location", {}).get("landing_page_url") or openalex_id,
                provider="openalex",
            ))
        return results

    @staticmethod
    def _openalex_id(value: str) -> str:
        value = value.rstrip("/").rsplit("/", 1)[-1]
        return value.split(":", 1)[-1] if value.lower().startswith("openalex:") else value

    def openalex_work(self, paper_id: str) -> dict[str, Any]:
        """Fetch one OpenAlex work, including its provider reference IDs."""
        work_id = self._openalex_id(paper_id)
        payload = self._get(f"https://api.openalex.org/works/{quote(work_id)}")
        doi = payload.get("doi")
        authors = [
            ((item.get("author") or {}).get("display_name") or "")
            for item in payload.get("authorships", [])
        ]
        canonical_id = f"openalex:{work_id}"
        arxiv_identity = extract_arxiv_identity(payload)
        arxiv_id = arxiv_identity.arxiv_id if arxiv_identity else None
        arxiv_location = next((location for location in payload.get("locations", [])
                               if "arxiv" in json.dumps(location, ensure_ascii=False).lower()), None)
        references = [
            f"openalex:{self._openalex_id(str(reference))}"
            for reference in payload.get("referenced_works", [])
            if reference
        ]
        return {
            "id": canonical_id,
            "title": payload.get("title") or "Untitled paper",
            "authors": [name for name in authors if name],
            "year": payload.get("publication_year"),
            "citation_count": int(payload.get("cited_by_count") or 0),
            "global_impact": float(payload.get("cited_by_count") or 0),
            "abstract": "",
            "url": payload.get("doi") or payload.get("id") or "",
            "keywords": [item.get("display_name", "") for item in payload.get("keywords", []) if item.get("display_name")],
            "metadata": {
                "provider": "openalex",
                "openalex_id": canonical_id,
                "doi": doi.replace("https://doi.org/", "") if isinstance(doi, str) else None,
                "arxiv_id": arxiv_id,
                "arxiv_identity_method": arxiv_identity.method if arxiv_identity else None,
                "arxiv_identity_evidence": arxiv_identity.evidence if arxiv_identity else None,
                "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None,
                "arxiv_pdf_url": f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None,
                "arxiv_location": bool(arxiv_location),
                "references": references,
                "reference_count": len(references),
                "verified_relations": True,
            },
        }

    def openalex_citing_works(self, paper_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return works that explicitly cite ``paper_id``."""
        work_id = self._openalex_id(paper_id)
        url = f"https://api.openalex.org/works?filter=cites:{quote(work_id)}&per-page={min(limit, 100)}"
        payload = self._get(url)
        return [self._search_item(item) for item in payload.get("results", []) if item.get("id")]

    def openalex_bibliographic_candidates(self, paper_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Find works sharing references with a seed (bibliographic coupling)."""
        seed = self.openalex_work(paper_id)
        reference_ids = list((seed.get("metadata") or {}).get("references") or [])[:8]
        counts: dict[str, tuple[int, dict[str, Any]]] = {}
        for reference_id in reference_ids:
            try:
                for paper in self.openalex_citing_works(reference_id, min(limit, 20)):
                    if paper["id"] == seed["id"]:
                        continue
                    count, existing = counts.get(paper["id"], (0, paper))
                    counts[paper["id"]] = (count + 1, existing)
            except Exception:
                continue
        ranked = sorted(counts.values(), key=lambda item: (-item[0], -int(item[1].get("citation_count") or 0)))
        result = []
        for count, paper in ranked[:limit]:
            paper["metadata"] = {**paper.get("metadata", {}), "discovered_from": seed["id"],
                                  "discovered_via": "bibliographic_coupling", "shared_reference_count": count}
            result.append(paper)
        return result

    def _search_item(self, item: dict[str, Any]) -> dict[str, Any]:
        openalex_id = str(item.get("id") or "")
        doi = item.get("doi")
        authors = [((author.get("author") or {}).get("display_name") or "") for author in item.get("authorships", [])]
        return self._paper(
            paper_id=f"openalex:{openalex_id.rsplit('/', 1)[-1]}",
            title=item.get("title") or "", authors=[name for name in authors if name],
            year=item.get("publication_year"),
            doi=doi.replace("https://doi.org/", "") if isinstance(doi, str) else None,
            url=item.get("doi") or item.get("primary_location", {}).get("landing_page_url") or openalex_id,
            provider="openalex",
        )

    def expand_openalex(self, paper_id: str, limit: int = 40) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Expand a seed through real OpenAlex citation directions.

        References are prior candidates; works returned by ``filter=cites`` are
        derivative candidates. Search results are only a bounded semantic
        supplement and never become citation edges by themselves.
        """
        seed = self.openalex_work(paper_id)
        seed_id = seed["id"]
        reference_ids = list(seed.get("metadata", {}).get("references", []))
        prior_budget = max(1, (limit - 1) // 3)
        derivative_budget = max(1, (limit - 1) // 3)
        related_budget = max(0, limit - 1 - prior_budget - derivative_budget)
        candidates: dict[str, dict[str, Any]] = {}

        def fetch_reference(reference_id: str) -> dict[str, Any] | None:
            try:
                return self.openalex_work(reference_id)
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=min(6, max(1, prior_budget))) as executor:
            fetched = executor.map(fetch_reference, reference_ids[:prior_budget])
        for paper in fetched:
            if paper is None:
                continue
            paper["metadata"] = {**paper.get("metadata", {}), "discovered_from": seed_id,
                                  "discovered_via": "references"}
            candidates[paper["id"]] = paper

        for paper in self.openalex_citing_works(seed_id, derivative_budget):
            paper["metadata"] = {**paper.get("metadata", {}), "discovered_from": seed_id,
                                  "discovered_via": "citations"}
            candidates[paper["id"]] = paper

        if related_budget:
            for paper in self.openalex_search(seed.get("title", ""), related_budget):
                if paper["id"] == seed_id or paper["id"] in candidates:
                    continue
                paper["metadata"] = {**paper.get("metadata", {}), "discovered_from": seed_id,
                                      "discovered_via": "related"}
                candidates[paper["id"]] = paper

        # Fetch full records for related/citing works so verified references are
        # available when two expanded candidates cite each other.
        to_enrich = [(candidate_id, candidate) for candidate_id, candidate in candidates.items()
                     if candidate.get("metadata", {}).get("discovered_via") != "references"]

        def enrich(item: tuple[str, dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
            candidate_id, candidate = item
            try:
                enriched = self.openalex_work(candidate_id)
                enriched["metadata"] = {**enriched.get("metadata", {}), **candidate.get("metadata", {})}
                return candidate_id, enriched
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=min(6, max(1, len(to_enrich)))) as executor:
            for result in executor.map(enrich, to_enrich):
                if result is not None:
                    candidates[result[0]] = result[1]
        return seed, list(candidates.values())[: max(0, limit - 1)]
