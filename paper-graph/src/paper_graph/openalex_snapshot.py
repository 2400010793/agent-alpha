"""Helpers for projecting OpenAlex Works snapshot records.

The current OpenAlex Work object does not reliably expose an ``ids.arxiv``
field.  arXiv identity is therefore resolved from explicit repository
locations and canonical arXiv DOIs before any title-based fallback is
considered.  This module deliberately contains no network access so it can be
used while streaming a pinned local snapshot.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


ARXIV_ID_PATTERN = r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Za-z-]+)?/\d{7})"
_ARXIV_VERSION_RE = re.compile(r"v(?P<version>\d+)$", re.IGNORECASE)
_ARXIV_VALUE_RE = re.compile(
    rf"(?i)(?:arxiv\.org/(?:abs|pdf)/|oai:arxiv\.org:|10\.48550/arxiv\.|arxiv:)?"
    rf"(?P<id>{ARXIV_ID_PATTERN})(?P<version>v\d+)?"
)


@dataclass(frozen=True)
class ArxivIdentity:
    """An exact arXiv identity extracted from OpenAlex metadata."""

    arxiv_id: str
    method: str
    evidence: str
    version: int | None = None
    confidence: str = "exact"


def _identity(value: Any, method: str, *, require_arxiv_marker: bool = True) -> ArxivIdentity | None:
    text = str(value or "").strip()
    if not text:
        return None
    lowered = text.casefold()
    if require_arxiv_marker and "arxiv" not in lowered and "10.48550" not in lowered:
        return None
    match = _ARXIV_VALUE_RE.search(text)
    if not match:
        return None
    raw_version = match.group("version") or ""
    version_match = _ARXIV_VERSION_RE.fullmatch(raw_version)
    return ArxivIdentity(
        arxiv_id=match.group("id"),
        method=method,
        evidence=text,
        version=int(version_match.group("version")) if version_match else None,
    )


def _locations(work: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for field in ("primary_location", "best_oa_location"):
        location = work.get(field)
        if isinstance(location, Mapping):
            yield field, location
    locations = work.get("locations")
    if isinstance(locations, list):
        for index, location in enumerate(locations):
            if isinstance(location, Mapping):
                yield f"locations[{index}]", location


def extract_arxiv_identity(work: Mapping[str, Any]) -> ArxivIdentity | None:
    """Extract an arXiv ID using only explicit OpenAlex identity evidence.

    The order intentionally prefers provider identifiers and repository
    locations over DOI inference.  No title matching is performed here.
    """
    ids = work.get("ids")
    if isinstance(ids, Mapping):
        identity = _identity(ids.get("arxiv"), "ids.arxiv", require_arxiv_marker=False)
        if identity:
            return identity

    for field, location in _locations(work):
        for key in ("id", "landing_page_url", "pdf_url"):
            identity = _identity(location.get(key), f"{field}.{key}")
            if identity:
                return identity

    identity = _identity(work.get("doi"), "doi")
    if identity:
        return identity
    return None


def reconstruct_abstract(index: Any) -> str:
    """Reconstruct OpenAlex's inverted abstract index into plain text."""
    if isinstance(index, str):
        try:
            index = json.loads(index)
        except json.JSONDecodeError:
            return ""
    if not isinstance(index, Mapping):
        return ""
    positioned: list[tuple[int, str]] = []
    for token, positions in index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and position >= 0:
                positioned.append((position, str(token)))
    positioned.sort(key=lambda item: item[0])
    return " ".join(token for _, token in positioned)


QUANT_TERMS = (
    "microstructure", "price_discovery", "price discovery", "price formation",
    "information asymmetry", "information-driven trading", "liquidity_provision",
    "liquidity provision", "liquidity demand", "liquidity supply", "liquidity resiliency",
    "liquidity resilience", "book_pressure_gradient", "order flow", "order-flow",
    "order-flow imbalance", "order imbalance", "order flow imbalance", "order flow toxicity",
    "quote imbalance", "queue imbalance", "depth imbalance", "depth profile",
    "order book shape", "order book slope", "book slope", "limit order", "market order",
    "order cancellation", "order replenishment", "hidden_liquidity", "hidden liquidity",
    "hidden orders", "iceberg order", "dark liquidity", "trade_toxicity", "trade toxicity",
    "informed trading", "adverse selection", "execution risk", "trading cost", "order book",
    "limit order book", "market depth", "bid-ask spread", "quoted spread", "effective spread",
    "liquidity imbalance", "liquidity risk", "market liquidity", "transaction costs",
    "execution cost", "optimal execution", "price impact", "market impact", "signed volume",
    "signed order flow", "signed trade", "trade sign", "trade arrival", "order arrival",
    "order cancellation rate", "Hawkes process", "VPIN", "intraday seasonality",
    "time-of-day effect", "volatility clustering", "realized volatility", "volatility shock",
    "volatility jump", "short-term reversal", "return reversal", "price continuation",
    "momentum effect", "price-volume", "trading volume", "volume shock", "volume-return",
    "intraday", "market making", "backtesting", "mean reversion", "walk-forward",
    "out-of-sample", "machine learning",
)


def _display_names(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return " ".join(
        str(item.get("display_name") or "")
        for item in value
        if isinstance(item, Mapping)
    )


def normalize_match_text(value: Any) -> str:
    """Normalize text and keyword aliases without losing phrase boundaries."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[_\N{HYPHEN}\N{NON-BREAKING HYPHEN}\N{EN DASH}\N{EM DASH}-]+", " ", text)
    return re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).strip()


def _matches(text: str, terms: Iterable[str]) -> list[str]:
    normalized = f" {normalize_match_text(text)} "
    return sorted({term for term in terms if f" {normalize_match_text(term)} " in normalized})


def _canonical_hit_count(hits: Iterable[str]) -> int:
    return len({normalize_match_text(hit) for hit in hits})


def classify_quant_work(
    work: Mapping[str, Any], *, terms: Iterable[str] = QUANT_TERMS, threshold: int = 4,
) -> dict[str, Any]:
    """Return an auditable lexical/topic prefilter for quantitative finance.

    This is intentionally a high-recall prefilter, not a final scientific
    taxonomy.  Title evidence receives the greatest weight, followed by
    OpenAlex keywords, topics, and the reconstructed abstract.
    """
    term_list = tuple(dict.fromkeys(str(term) for term in terms if str(term).strip()))
    title_hits = _matches(str(work.get("title") or ""), term_list)
    keyword_hits = _matches(_display_names(work.get("keywords")), term_list)
    topic_hits = _matches(
        " ".join(filter(None, [
            _display_names(work.get("topics")),
            str((work.get("primary_topic") or {}).get("display_name") or "")
            if isinstance(work.get("primary_topic"), Mapping) else "",
        ])),
        term_list,
    )
    abstract_hits = _matches(reconstruct_abstract(work.get("abstract_inverted_index")), term_list)
    # Alias spellings (for example ``order-flow`` and ``order flow``) remain
    # visible as evidence but count only once toward ranking.
    score = (
        4 * _canonical_hit_count(title_hits)
        + 3 * _canonical_hit_count(keyword_hits)
        + 2 * _canonical_hit_count(topic_hits)
        + _canonical_hit_count(abstract_hits)
    )
    has_match = any((title_hits, keyword_hits, topic_hits, abstract_hits))
    return {
        "is_quant_candidate": has_match,
        "passes_score_threshold": score >= threshold,
        "quant_score": score,
        "matched_title_terms": title_hits,
        "matched_keyword_terms": keyword_hits,
        "matched_topic_terms": topic_hits,
        "matched_abstract_terms": abstract_hits,
        "threshold": threshold,
        "selection_version": "openalex_quant_prefilter_v1",
    }