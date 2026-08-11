"""Canonicalization helpers for external paper identifiers."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse


_ARXIV_PREFIX = re.compile(r"^(?:arxiv:)?(.+)$", re.IGNORECASE)


def normalize_arxiv_id(value: str) -> str:
    """Return an arXiv identifier without URL, version, or prefix noise."""
    text = unquote(value).strip()
    if not text:
        raise ValueError("arXiv identifier cannot be empty")

    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        text = parsed.path.strip("/")
        if text.startswith("abs/") or text.startswith("pdf/"):
            text = text.split("/", 1)[1]

    match = _ARXIV_PREFIX.match(text)
    assert match is not None
    text = match.group(1).strip().removesuffix(".pdf")
    text = re.sub(r"v\d+$", "", text, flags=re.IGNORECASE)
    if not text:
        raise ValueError("arXiv identifier cannot be empty")
    return text


def canonical_paper_id(*, arxiv: str | None = None, doi: str | None = None,
                       openalex: str | None = None,
                       semantic_scholar: str | None = None) -> str:
    """Choose a stable local key, preferring arXiv then DOI then providers."""
    if arxiv:
        return f"arxiv:{normalize_arxiv_id(arxiv)}"
    if doi:
        return f"doi:{doi.strip().lower().removeprefix('https://doi.org/')}"
    if openalex:
        return f"openalex:{openalex.strip()}"
    if semantic_scholar:
        return f"s2:{semantic_scholar.strip()}"
    raise ValueError("at least one paper identifier is required")
