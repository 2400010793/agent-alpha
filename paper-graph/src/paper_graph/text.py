"""Build the paper text used by local semantic embedding models."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping


def normalize_keywords(keywords: Iterable[str] | str | None) -> tuple[str, ...]:
    """Normalize, de-duplicate, and preserve the order of paper keywords."""
    if keywords is None:
        return ()
    values = [keywords] if isinstance(keywords, str) else keywords
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = re.sub(r"\s+", " ", str(value)).strip()
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


def build_embedding_text(paper: Mapping[str, object]) -> tuple[str, str]:
    """Return ``(text, quality)`` from title, abstract, and digest evidence."""
    title = re.sub(r"\s+", " ", str(paper.get("title", ""))).strip()
    abstract = re.sub(r"\s+", " ", str(paper.get("abstract", ""))).strip()
    keywords = normalize_keywords(paper.get("keywords"))  # type: ignore[arg-type]
    metadata = paper.get("metadata") if isinstance(paper.get("metadata"), Mapping) else {}
    digest = metadata.get("digest") if isinstance(metadata, Mapping) else {}
    digest = digest if isinstance(digest, Mapping) else {}
    research_problem = str(digest.get("research_question", "")).strip()
    method = str(digest.get("method", "")).strip()
    if not title and not abstract and not keywords and not research_problem and not method:
        raise ValueError("paper needs text for embedding")
    parts = []
    if title:
        parts.append(f"Title: {title}")
    if abstract:
        parts.append(f"Abstract: {abstract}")
    if keywords:
        parts.append(f"Keywords: {'; '.join(keywords)}")
    if research_problem:
        parts.append(f"Research problem: {research_problem}")
    if method:
        parts.append(f"Method: {method}")
    quality = "A" if title and (abstract or keywords) else "B" if title else "C"
    return "\n".join(parts), quality