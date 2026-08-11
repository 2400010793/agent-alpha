"""Deterministic research-value ranking for finance retrieval candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from paper_graph.finance_audit import NON_RESEARCH_WORK_TYPES, FinanceAuditDecision
from paper_graph.openalex_snapshot import normalize_match_text, reconstruct_abstract


RESEARCH_VALUE_VERSION = "quant_research_value_v1"

CORE_TERMS = {
    "bid ask spread", "limit order book", "market impact", "market microstructure",
    "optimal execution", "order book", "order flow", "order flow imbalance",
    "price discovery", "price impact", "realized volatility",
}
STRATEGY_TERMS = {
    "algorithmic trading", "asset pricing", "foreign exchange", "mean reversion",
    "momentum", "portfolio management", "portfolio optimization", "systematic risk",
    "trading strategy",
}
RIGOR_TERMS = {
    "backtest", "changepoint", "garch", "har rv", "high frequency",
    "jump", "out of sample", "reinforcement learning", "sharpe",
}
LOW_VALUE_PATTERNS = {
    "advisory chatbot", "chatbot service", "comparison of machine learning models",
    "stock price prediction system",
}


@dataclass(frozen=True)
class ResearchValueDecision:
    tier: str
    score: int
    reasons: tuple[str, ...]
    version: str = RESEARCH_VALUE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hits(text: str, terms: set[str]) -> tuple[str, ...]:
    padded = f" {normalize_match_text(text)} "
    return tuple(sorted(term for term in terms if f" {term} " in padded))


def assess_research_value(
    work: Mapping[str, Any], finance: FinanceAuditDecision
) -> ResearchValueDecision:
    """Rank accepted research deterministically without calling an LLM."""
    work_type = normalize_match_text(work.get("type") or "")
    if work_type in NON_RESEARCH_WORK_TYPES:
        return ResearchValueDecision("exclude", 0, (f"non_research_work_type:{work_type}",))
    if finance.status == "rejected":
        return ResearchValueDecision("exclude", 0, ("finance_status:rejected",))
    if finance.status != "accepted":
        return ResearchValueDecision("unknown", 0, (f"finance_status:{finance.status}",))

    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    text = " ".join((str(work.get("title") or ""), abstract))
    core = _hits(text, CORE_TERMS)
    strategy = _hits(text, STRATEGY_TERMS)
    rigor = _hits(text, RIGOR_TERMS)
    low = _hits(text, LOW_VALUE_PATTERNS)
    has_citations = bool(
        work.get("referenced_works")
        or work.get("referenced_works_count")
        or work.get("cited_by_count")
    )
    has_exact_identity = bool(work.get("arxiv_id") or work.get("doi"))

    score = 0
    reasons: list[str] = []
    if core:
        score += 4
        reasons.extend(f"core:{term}" for term in core)
    if strategy:
        score += 2
        reasons.extend(f"strategy:{term}" for term in strategy)
    if rigor:
        score += 2
        reasons.extend(f"rigor:{term}" for term in rigor)
    if abstract:
        score += 1
        reasons.append("has_abstract")
    if has_citations:
        score += 1
        reasons.append("has_citation_evidence")
    if has_exact_identity:
        score += 1
        reasons.append("has_exact_external_identity")
    if low:
        score -= 3
        reasons.extend(f"low_value_pattern:{term}" for term in low)

    if core and score >= 5:
        tier = "high"
    elif strategy and rigor and score >= 6:
        tier = "high"
    elif score >= 3:
        tier = "medium"
    else:
        tier = "low"
    return ResearchValueDecision(tier, score, tuple(reasons or ("limited_value_evidence",)))


__all__ = [
    "RESEARCH_VALUE_VERSION",
    "ResearchValueDecision",
    "assess_research_value",
]
