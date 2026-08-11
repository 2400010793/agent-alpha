"""Conservative finance audit for the high-recall OpenAlex corpus.

The exact 85-term vocabulary remains the retrieval superset. OpenAlex-generated
keywords/topics can trigger review, but cannot by themselves auto-accept a
paper because the Gate 2 sample showed substantial cross-domain leakage.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from paper_graph.openalex_snapshot import normalize_match_text, reconstruct_abstract


FINANCE_AUDIT_VERSION = "finance_audit_v4"

# The production corpus is a research-paper corpus. These OpenAlex Work types
# may be useful discovery evidence, but should not be promoted as papers.
NON_RESEARCH_WORK_TYPES = {
    "book", "dataset", "editorial", "erratum", "libguides", "paratext",
    "peer-review", "software", "standard",
}

GENERIC_TERMS = {
    "backtesting", "intraday", "machine learning", "out of sample", "walk forward",
}

DIRECT_QUANT_TERMS = {
    "adverse selection", "bid ask spread", "dark liquidity", "depth imbalance",
    "effective spread", "execution cost", "hidden liquidity", "iceberg order",
    "limit order book", "liquidity imbalance", "liquidity provision", "market impact",
    "market making", "optimal execution", "order book", "order book shape",
    "order book slope", "order cancellation", "order flow", "order flow imbalance",
    "order flow toxicity", "price impact", "quote imbalance", "queue imbalance",
    "signed order flow", "trade sign", "trade toxicity", "trading cost", "vpin",
}

# Automatic acceptance from a title is restricted to phrases whose ordinary
# meaning is itself a quantitative trading/microstructure object. Broader
# finance concepts such as adverse selection, market making and liquidity
# provision remain review evidence.
HIGH_PRECISION_TITLE_TERMS = {
    "bid ask spread", "dark liquidity", "depth imbalance", "effective spread",
    "execution cost", "hidden liquidity", "iceberg order", "limit order book",
    "liquidity imbalance", "market impact", "optimal execution", "order book",
    "order book shape", "order book slope", "order cancellation", "order flow",
    "order flow imbalance", "order flow toxicity", "price impact", "quote imbalance",
    "queue imbalance", "signed order flow", "trade sign", "trade toxicity",
    "trading cost", "vpin",
}

CONTEXTUAL_QUANT_TERMS = {
    "information asymmetry", "intraday", "liquidity risk", "liquidity supply",
    "machine learning", "market depth", "market liquidity", "mean reversion",
    "microstructure", "momentum effect", "out of sample", "price discovery",
    "price formation", "realized volatility", "return reversal", "short term reversal",
    "trading volume", "transaction costs", "volatility clustering", "volatility jump",
    "volatility shock", "walk forward",
}

# Broad single words such as market, portfolio, volatility, risk, price and
# return are intentionally excluded from automatic acceptance evidence.
TRADING_MARKET_CONTEXTS = {
    "algorithmic trading", "asset pricing", "asset return", "bid ask", "bond market",
    "capital market", "commodity futures", "cryptocurrency market", "equity market",
    "exchange traded", "financial market", "foreign exchange", "forex market",
    "futures market", "high frequency data", "high frequency trading", "limit order",
    "market liquidity", "market microstructure", "option market", "order book", "order flow",
    "portfolio management", "security return", "stock market", "stock price",
    "stock return", "stock trading", "trade execution", "trading strategy",
}

NEGATIVE_CONTEXTS = {
    "agricultural", "battery storage", "brain", "cancer", "ceramic", "clinical",
    "computer network", "disease", "ecology", "electricity", "energy dispatch",
    "fault diagnosis", "gene expression", "healthcare", "image classification",
    "medical", "medical imaging", "microgrid", "molecular", "power grid", "protein",
    "quantum computing", "speech recognition", "traffic flow", "weather forecasting",
    "wildfire", "wireless network",
}

AMBIGUOUS_FINANCE_CONTEXTS = {
    "bank liquidity", "banking regulation", "balance sheet", "bankruptcy",
    "cash holding", "corporate finance", "corporate liquidity", "credit risk",
    "dividend payout", "financial inclusion", "financial reporting", "funding liquidity",
    "liquidity funds", "profitability", "tax aggressiveness",
}


@dataclass(frozen=True)
class FinanceAuditDecision:
    status: str
    reasons: tuple[str, ...]
    finance_anchors: tuple[str, ...] = ()
    negative_contexts: tuple[str, ...] = ()
    acceptance_score: int = 0
    authored_match_fields: tuple[str, ...] = ()
    audit_version: str = FINANCE_AUDIT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _display_names(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return " ".join(
        str(item.get("display_name") or "")
        for item in value
        if isinstance(item, Mapping)
    )


def _field_texts(work: Mapping[str, Any]) -> dict[str, str]:
    primary_topic = work.get("primary_topic")
    primary_name = (
        str(primary_topic.get("display_name") or "")
        if isinstance(primary_topic, Mapping)
        else ""
    )
    return {
        "title": normalize_match_text(work.get("title") or work.get("display_name") or ""),
        "abstract": normalize_match_text(reconstruct_abstract(work.get("abstract_inverted_index"))),
        "keyword": normalize_match_text(_display_names(work.get("keywords"))),
        "topic": normalize_match_text(f"{_display_names(work.get('topics'))} {primary_name}"),
    }


def _phrases(text: str, vocabulary: set[str]) -> tuple[str, ...]:
    padded = f" {text} "
    return tuple(sorted(term for term in vocabulary if f" {term} " in padded))


def _matches(match: Mapping[str, Any], key: str) -> set[str]:
    return {
        normalize_match_text(term)
        for term in match.get(key, [])
        if normalize_match_text(term)
    }


def audit_finance_context(
    work: Mapping[str, Any], match: Mapping[str, Any]
) -> FinanceAuditDecision:
    """Assign a conservative status without removing retrieval records."""
    texts = _field_texts(work)
    all_text = " ".join(texts.values())
    negatives = _phrases(all_text, NEGATIVE_CONTEXTS)
    ambiguous = _phrases(all_text, AMBIGUOUS_FINANCE_CONTEXTS)
    title_contexts = _phrases(texts["title"], TRADING_MARKET_CONTEXTS)
    abstract_contexts = _phrases(texts["abstract"], TRADING_MARKET_CONTEXTS)
    contexts = tuple(sorted(set(title_contexts) | set(abstract_contexts)))

    title_hits = _matches(match, "matched_title_terms")
    abstract_hits = _matches(match, "matched_abstract_terms")
    metadata_hits = _matches(match, "matched_keyword_terms") | _matches(match, "matched_topic_terms")
    authored_hits = title_hits | abstract_hits
    direct_title = title_hits & DIRECT_QUANT_TERMS
    direct_abstract = abstract_hits & DIRECT_QUANT_TERMS
    high_precision_title = direct_title & HIGH_PRECISION_TITLE_TERMS
    contextual_authored = authored_hits & CONTEXTUAL_QUANT_TERMS
    authored_fields = tuple(
        field for field, hits in (("title", title_hits), ("abstract", abstract_hits)) if hits
    )

    work_type = normalize_match_text(work.get("type") or "")
    if work_type in NON_RESEARCH_WORK_TYPES:
        return FinanceAuditDecision(
            "rejected", (f"non_research_work_type:{work_type}",),
            authored_match_fields=authored_fields,
        )

    # Only authored title/abstract evidence contributes to acceptance.
    score = 0
    score += 6 if direct_title else 0
    score += 4 if direct_abstract else 0
    score += 3 if title_contexts else 0
    score += 2 if abstract_contexts else 0
    score += 2 if contextual_authored else 0
    score += 1 if len(authored_hits) >= 2 else 0

    common = {
        "acceptance_score": score,
        "authored_match_fields": authored_fields,
    }
    if negatives and not contexts:
        return FinanceAuditDecision(
            "rejected", tuple(f"negative_context:{term}" for term in negatives),
            negative_contexts=negatives, **common,
        )
    if negatives:
        return FinanceAuditDecision(
            "review", ("conflicting_trading_market_and_negative_context",),
            finance_anchors=contexts, negative_contexts=negatives, **common,
        )
    if ambiguous and not high_precision_title:
        return FinanceAuditDecision(
            "review", tuple(f"ambiguous_finance_context:{term}" for term in ambiguous),
            finance_anchors=contexts, **common,
        )
    if not authored_hits and metadata_hits:
        return FinanceAuditDecision(
            "review", ("metadata_only_keyword_or_topic_match",),
            finance_anchors=contexts, **common,
        )
    # Broad financial titles without an abstract or any local citation evidence
    # remain discoverable but are not promoted automatically. High-precision
    # microstructure phrases are exempt because their title meaning is direct.
    has_citation_evidence = bool(
        work.get("referenced_works")
        or work.get("referenced_works_count")
        or work.get("cited_by_count")
    )
    if not texts["abstract"] and not has_citation_evidence and not high_precision_title:
        return FinanceAuditDecision(
            "review", ("insufficient_local_evidence_for_auto_accept",),
            finance_anchors=tuple(sorted(set(contexts) | direct_title)), **common,
        )
    if high_precision_title and score >= 6:
        return FinanceAuditDecision(
            "accepted", tuple(f"high_precision_quant_title:{term}" for term in sorted(high_precision_title)),
            finance_anchors=tuple(sorted(set(contexts) | high_precision_title)), **common,
        )
    if contextual_authored and title_contexts and score >= 5:
        return FinanceAuditDecision(
            "accepted",
            tuple(f"contextual_quant_with_title_market_context:{term}" for term in sorted(contextual_authored)),
            finance_anchors=contexts, **common,
        )
    if authored_hits <= GENERIC_TERMS and not title_contexts:
        reason = "generic_keyword_without_title_trading_market_context"
    elif contexts:
        reason = "authored_quant_match_below_acceptance_threshold"
    else:
        reason = "authored_match_without_trading_market_context"
    review_anchors = tuple(sorted(set(contexts) | direct_title | direct_abstract))
    return FinanceAuditDecision("review", (reason,), finance_anchors=review_anchors, **common)


__all__ = [
    "FINANCE_AUDIT_VERSION",
    "NON_RESEARCH_WORK_TYPES",
    "FinanceAuditDecision",
    "audit_finance_context",
]
