"""Deterministic Graph and Digest seed selection from audited candidates."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from paper_graph.openalex_snapshot import normalize_match_text


SEED_SELECTION_VERSION = "openalex_seed_selection_v1"
RESEARCH_TYPES = {"article", "book-chapter", "dissertation", "preprint", "report", "review"}
FINANCE_TITLE_TERMS = {
    "algorithmic trading", "asset pricing", "bid ask spread", "bond market", "financial time series",
    "crypto asset", "digital asset", "exchange rate", "financial market",
    "foreign exchange", "limit order book", "market liquidity", "market microstructure",
    "liquidity boursiere", "optimal execution", "order book", "order flow", "portfolio", "price discovery",
    "reinforcement learning based trading",
    "realized volatility", "stock market", "stock price", "stock return", "stock trading",
    "trading cost", "trading strategy", "trading volume",
}


def _has_finance_title(row: Mapping[str, Any]) -> bool:
    title = f" {normalize_match_text(row.get('title') or '')} "
    return any(f" {term} " in title for term in FINANCE_TITLE_TERMS)


def _dedupe_key(row: Mapping[str, Any]) -> str:
    return normalize_match_text(row.get("title") or row.get("openalex_id") or "")


def _rank(row: Mapping[str, Any]) -> tuple[Any, ...]:
    tier = {"high": 3, "medium": 2, "low": 1}.get(str(row.get("research_value_tier")), 0)
    return (
        tier,
        int(row.get("research_value_score") or 0),
        int(row.get("finance_acceptance_score") or 0),
        int((row.get("quant_match") or {}).get("quant_score") or 0),
        int(row.get("cited_by_count") or 0),
        int(row.get("referenced_works_count") or 0),
        str(row.get("openalex_id") or ""),
    )


def _seed_row(row: Mapping[str, Any], *, seed_type: str, selection_status: str) -> dict[str, Any]:
    return {
        "schema_version": SEED_SELECTION_VERSION,
        "seed_type": seed_type,
        "selection_status": selection_status,
        "canonical_paper_id": row.get("canonical_paper_id"),
        "openalex_id": row.get("openalex_id"),
        "arxiv_id": row.get("arxiv_id"),
        "doi": row.get("doi"),
        "title": row.get("title"),
        "publication_year": row.get("publication_year"),
        "finance_status": row.get("finance_status"),
        "finance_audit_version": row.get("finance_audit_version"),
        "finance_acceptance_score": row.get("finance_acceptance_score"),
        "research_value_tier": row.get("research_value_tier"),
        "research_value_score": row.get("research_value_score"),
        "research_value_version": row.get("research_value_version"),
        "referenced_works_count": row.get("referenced_works_count") or 0,
        "cited_by_count": row.get("cited_by_count") or 0,
        "selection_reason": (
            "v4_seed_eligible"
            if selection_status == "approved"
            else "deterministic_finance_title_expansion_candidate"
        ),
    }


def select_seed_manifests(
    rows: Iterable[Mapping[str, Any]], *, graph_target: int = 30, digest_target: int = 5
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = [dict(row) for row in rows]
    approved = sorted(
        (row for row in candidates if row.get("graph_seed_eligible")), key=_rank, reverse=True
    )
    expansion = sorted(
        (
            row for row in candidates
            if row.get("finance_status") == "review"
            and str(row.get("type") or "") in RESEARCH_TYPES
            and not row.get("finance_negative_contexts")
            and _has_finance_title(row)
            and bool(row.get("referenced_works_count") or row.get("cited_by_count") or row.get("arxiv_id"))
        ),
        key=_rank,
        reverse=True,
    )
    graph: list[dict[str, Any]] = []
    seen: set[str] = set()
    for status, values in (("approved", approved), ("expansion_candidate", expansion)):
        for row in values:
            key = _dedupe_key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            graph.append(_seed_row(row, seed_type="graph", selection_status=status))
            if len(graph) >= graph_target:
                break
        if len(graph) >= graph_target:
            break
    for rank, row in enumerate(graph, 1):
        row["seed_rank"] = rank

    by_id = {str(row.get("openalex_id")): row for row in candidates}
    digest_pool = [
        row for row in graph
        if row.get("arxiv_id") and row.get("selection_status") == "approved"
    ] + [
        row for row in graph
        if row.get("arxiv_id") and row.get("selection_status") != "approved"
    ]
    digest: list[dict[str, Any]] = []
    for selected in digest_pool[:digest_target]:
        source = by_id[str(selected["openalex_id"])]
        digest.append(_seed_row(
            source,
            seed_type="digest",
            selection_status=str(selected["selection_status"]),
        ))
    for rank, row in enumerate(digest, 1):
        row["seed_rank"] = rank
    return graph, digest


__all__ = ["SEED_SELECTION_VERSION", "select_seed_manifests"]
