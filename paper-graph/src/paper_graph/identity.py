"""Exact paper identity resolution and deterministic OpenAlex deduplication."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlparse

from .normalize import normalize_arxiv_id
from .openalex_snapshot import extract_arxiv_identity


_DOI_RE = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)


def normalize_doi(value: Any) -> str | None:
    """Return a lower-case bare DOI, or ``None`` for non-DOI values."""
    text = unquote(str(value or "")).strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc and parsed.netloc.casefold() in {"doi.org", "dx.doi.org"}:
        text = parsed.path.lstrip("/")
    text = re.sub(r"^(?:doi:\s*)", "", text, flags=re.IGNORECASE)
    match = _DOI_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;)").casefold()


def normalize_openalex_id(value: Any) -> str | None:
    """Return a bare OpenAlex Work ID such as ``W123``."""
    text = str(value or "").strip().rstrip("/")
    if not text:
        return None
    text = text.rsplit("/", 1)[-1]
    text = re.sub(r"^openalex:", "", text, flags=re.IGNORECASE)
    return text.upper() if re.fullmatch(r"w\d+", text, flags=re.IGNORECASE) else None


@dataclass(frozen=True)
class ResolvedIdentity:
    canonical_paper_id: str
    openalex_id: str | None
    arxiv_id: str | None
    doi: str | None
    method: str
    evidence: str
    confidence: str = "exact"


def resolve_identity(record: Mapping[str, Any]) -> ResolvedIdentity:
    """Resolve a record without fuzzy title matching."""
    openalex_id = normalize_openalex_id(record.get("openalex_id") or record.get("id"))
    raw_arxiv = record.get("arxiv_id")
    arxiv_id: str | None = None
    method = ""
    evidence = ""
    if raw_arxiv:
        arxiv_id = normalize_arxiv_id(str(raw_arxiv))
        method = str(record.get("identity_method") or "arxiv_id")
        evidence = str(record.get("identity_evidence") or raw_arxiv)
    else:
        extracted = extract_arxiv_identity(record)
        if extracted:
            arxiv_id = normalize_arxiv_id(extracted.arxiv_id)
            method = extracted.method
            evidence = extracted.evidence
    doi = normalize_doi(record.get("doi"))
    if arxiv_id:
        canonical = f"arxiv:{arxiv_id}"
    elif doi:
        canonical = f"doi:{doi}"
        method = method or "doi"
        evidence = evidence or str(record.get("doi"))
    elif openalex_id:
        canonical = f"openalex:{openalex_id}"
        method = method or "openalex"
        evidence = evidence or str(record.get("openalex_id") or record.get("id"))
    else:
        raise ValueError("record has no exact arXiv, DOI, or OpenAlex identity")
    return ResolvedIdentity(canonical, openalex_id, arxiv_id, doi, method, evidence)


def _record_rank(record: Mapping[str, Any]) -> tuple[int, int, int, int, int, str]:
    identity = resolve_identity(record)
    metadata_fields = (
        "title", "authorships", "authors", "publication_year", "abstract_inverted_index",
        "topics", "keywords", "referenced_works",
    )
    completeness = sum(record.get(field) not in (None, "", [], {}) for field in metadata_fields)
    published_version = int(any(
        str((location or {}).get("version") or "").casefold() == "publishedversion"
        for location in record.get("locations") or [] if isinstance(location, Mapping)
    ))
    safe = int(not any(bool(record.get(field)) for field in ("is_retracted", "is_paratext", "is_xpac")))
    exact_ids = int(identity.arxiv_id is not None) + int(identity.doi is not None)
    citations = max(0, int(record.get("cited_by_count") or record.get("citation_count") or 0))
    return safe, exact_ids, published_version, completeness, citations, identity.openalex_id or ""


class _DisjointSet:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def group_exact_identities(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Group records connected by exact arXiv IDs or exact normalized DOIs.

    OpenAlex-only records remain separate. A group representative is selected
    deterministically, but every member and the exact merge keys are retained.
    """
    rows = [dict(record) for record in records]
    identities = [resolve_identity(record) for record in rows]
    disjoint = _DisjointSet(len(rows))
    indexes: dict[tuple[str, str], int] = {}
    for index, identity in enumerate(identities):
        keys = []
        if identity.arxiv_id:
            keys.append(("arxiv", identity.arxiv_id))
        if identity.doi:
            keys.append(("doi", identity.doi))
        for key in keys:
            if key in indexes:
                disjoint.union(index, indexes[key])
            else:
                indexes[key] = index

    grouped: dict[int, list[int]] = {}
    for index in range(len(rows)):
        grouped.setdefault(disjoint.find(index), []).append(index)
    result = []
    for member_indexes in grouped.values():
        representative_index = max(member_indexes, key=lambda index: _record_rank(rows[index]))
        member_identities = [identities[index] for index in member_indexes]
        representative = identities[representative_index]
        arxiv_ids = sorted({identity.arxiv_id for identity in member_identities if identity.arxiv_id})
        dois = sorted({identity.doi for identity in member_identities if identity.doi})
        openalex_ids = sorted({identity.openalex_id for identity in member_identities if identity.openalex_id})
        result.append({
            "canonical_paper_id": representative.canonical_paper_id,
            "representative_openalex_id": representative.openalex_id,
            "member_openalex_ids": openalex_ids,
            "arxiv_ids": arxiv_ids,
            "dois": dois,
            "member_count": len(member_indexes),
            "merge_methods": (["arxiv"] if arxiv_ids else []) + (["doi"] if dois else []),
            "members": [rows[index] for index in member_indexes],
        })
    return sorted(result, key=lambda group: group["canonical_paper_id"])