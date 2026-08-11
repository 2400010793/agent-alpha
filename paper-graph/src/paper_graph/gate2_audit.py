"""Deterministic Gate 2 summaries and review samples for OpenAlex retrieval."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from paper_graph.filter_profiles import get_filter_profile
from paper_graph.openalex_snapshot import normalize_match_text


FOCUS_TERMS = ("machine learning", "intraday", "market liquidity")
MATCH_FIELDS = {
    "title": "matched_title_terms",
    "keyword": "matched_keyword_terms",
    "topic": "matched_topic_terms",
    "abstract": "matched_abstract_terms",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_candidate_rows(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict) or not row.get("openalex_id"):
                    raise ValueError(f"invalid candidate row: {path}:{line_number}")
                rows.append(row)
    return rows


def _canonical_hits(match: Mapping[str, Any]) -> set[str]:
    return {
        normalize_match_text(term)
        for key in MATCH_FIELDS.values()
        for term in match.get(key, [])
        if normalize_match_text(term)
    }


def _matched_fields(match: Mapping[str, Any]) -> list[str]:
    return [name for name, key in MATCH_FIELDS.items() if match.get(key)]


def reaudit_row(row: Mapping[str, Any], *, filter_profile: str = "v4") -> dict[str, Any]:
    profile = get_filter_profile(filter_profile)
    existing_match = row.get("quant_match") if isinstance(row.get("quant_match"), Mapping) else {}
    match = profile.classify(row) if filter_profile != "v4" else existing_match
    decision = profile.audit(row, match)
    value = profile.assess_value(row, decision)
    references = row.get("referenced_works") or []
    graph_seed_eligible = (
        decision.status == "accepted"
        and value.tier in {"high", "medium"}
        and not any(bool(row.get(field)) for field in ("is_retracted", "is_paratext", "is_xpac"))
        and bool(references or row.get("referenced_works_count") or row.get("cited_by_count"))
    )
    digest_seed_eligible = (
        decision.status == "accepted"
        and value.tier in {"high", "medium"}
        and bool(row.get("arxiv_id"))
    )
    return {
        **dict(row),
        "quant_match": match,
        "selection_version": profile.selection_version,
        "retrieval_retained": bool(match.get("is_quant_candidate")),
        "previous_graph_seed_eligible": bool(row.get("graph_seed_eligible")),
        "previous_digest_seed_eligible": bool(row.get("digest_seed_eligible")),
        "previous_finance_status": str(row.get("finance_status") or ""),
        "finance_status": decision.status,
        "finance_audit_reasons": list(decision.reasons),
        "finance_audit_version": decision.audit_version,
        "finance_anchors": list(decision.finance_anchors),
        "finance_negative_contexts": list(decision.negative_contexts),
        "finance_acceptance_score": decision.acceptance_score,
        "finance_authored_match_fields": list(decision.authored_match_fields),
        "finance_review_priority": getattr(decision, "review_priority", "none"),
        "finance_review_priority_score": getattr(decision, "review_priority_score", 0),
        "research_value_tier": value.tier,
        "research_value_score": value.score,
        "research_value_reasons": list(value.reasons),
        "research_value_version": value.version,
        "graph_seed_eligible": graph_seed_eligible,
        "digest_seed_eligible": digest_seed_eligible,
    }


def build_gate2_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    materialized = [dict(row) for row in rows]
    status_counts: Counter[str] = Counter()
    previous_status_counts: Counter[str] = Counter()
    transition_counts: Counter[str] = Counter()
    keyword_counts: Counter[str] = Counter()
    field_counts: Counter[str] = Counter()
    year_counts: Counter[str] = Counter()
    value_tier_counts: Counter[str] = Counter()
    review_priority_counts: Counter[str] = Counter()
    keyword_status: dict[str, Counter[str]] = defaultdict(Counter)
    openalex_ids: set[str] = set()

    for row in materialized:
        openalex_id = str(row.get("openalex_id") or "")
        if openalex_id in openalex_ids:
            raise ValueError(f"duplicate OpenAlex ID in Gate 2 input: {openalex_id}")
        openalex_ids.add(openalex_id)
        status = str(row.get("finance_status") or "")
        previous = str(row.get("previous_finance_status") or status)
        status_counts[status] += 1
        previous_status_counts[previous] += 1
        transition_counts[f"{previous}->{status}"] += 1
        year_counts[str(row.get("publication_year") or "unknown")] += 1
        value_tier_counts[str(row.get("research_value_tier") or "unknown")] += 1
        if status == "review":
            review_priority_counts[str(row.get("finance_review_priority") or "none")] += 1
        match = row.get("quant_match") if isinstance(row.get("quant_match"), Mapping) else {}
        for field_name in _matched_fields(match):
            field_counts[field_name] += 1
        for term in _canonical_hits(match):
            keyword_counts[term] += 1
            keyword_status[term][status] += 1

    return {
        "schema_version": "openalex_gate2_summary_v1",
        "finance_audit_version": next(
            (str(row.get("finance_audit_version")) for row in materialized if row.get("finance_audit_version")),
            "unknown",
        ),
        "retrieval_count": len(materialized),
        "retrieval_retained_count": sum(bool(row.get("retrieval_retained", True)) for row in materialized),
        "retrieval_demoted_count": sum(not bool(row.get("retrieval_retained", True)) for row in materialized),
        "retrieval_tier": dict(sorted(Counter(
            str((row.get("quant_match") or {}).get("retrieval_tier") or "legacy")
            for row in materialized
        ).items())),
        "unique_openalex_id_count": len(openalex_ids),
        "finance_status": dict(sorted(status_counts.items())),
        "previous_finance_status": dict(sorted(previous_status_counts.items())),
        "status_transitions": dict(sorted(transition_counts.items())),
        "with_arxiv": sum(bool(row.get("arxiv_id")) for row in materialized),
        "retained_with_arxiv": sum(
            bool(row.get("arxiv_id")) and bool(row.get("retrieval_retained", True))
            for row in materialized
        ),
        "research_value_version": next(
            (str(row.get("research_value_version")) for row in materialized if row.get("research_value_version")),
            "unknown",
        ),
        "research_value_tier": dict(sorted(value_tier_counts.items())),
        "review_priority": dict(sorted(review_priority_counts.items())),
        "graph_seed_eligible": sum(bool(row.get("graph_seed_eligible")) for row in materialized),
        "digest_seed_eligible": sum(bool(row.get("digest_seed_eligible")) for row in materialized),
        "graph_seed_eligible_previous": sum(bool(row.get("previous_graph_seed_eligible")) for row in materialized),
        "digest_seed_eligible_previous": sum(bool(row.get("previous_digest_seed_eligible")) for row in materialized),
        "matched_field_counts": dict(sorted(field_counts.items())),
        "publication_year_counts": dict(sorted(year_counts.items())),
        "canonical_keyword_counts": dict(sorted(keyword_counts.items())),
        "canonical_keyword_status": {
            term: dict(sorted(counts.items())) for term, counts in sorted(keyword_status.items())
        },
    }


def _stable_rank(row: Mapping[str, Any], seed: int) -> str:
    value = f"{seed}:{row.get('openalex_id', '')}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _strata(row: Mapping[str, Any]) -> set[str]:
    match = row.get("quant_match") if isinstance(row.get("quant_match"), Mapping) else {}
    terms = _canonical_hits(match)
    strata = {f"status:{row.get('finance_status', '')}"}
    strata.update(f"field:{field}" for field in _matched_fields(match))
    strata.update(f"focus:{term}" for term in FOCUS_TERMS if term in terms)
    return strata


def build_stratified_review_sample(
    rows: Iterable[Mapping[str, Any]], *, sample_size: int = 180, random_seed: int = 20260810
) -> list[dict[str, Any]]:
    candidates = [dict(row) for row in rows]
    by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        for stratum in _strata(row):
            by_stratum[stratum].append(row)
    for values in by_stratum.values():
        values.sort(key=lambda row: _stable_rank(row, random_seed))

    selected: dict[str, dict[str, Any]] = {}
    offsets = {stratum: 0 for stratum in by_stratum}
    strata = sorted(by_stratum)
    while len(selected) < min(sample_size, len(candidates)):
        progressed = False
        for stratum in strata:
            values = by_stratum[stratum]
            offset = offsets[stratum]
            while offset < len(values) and str(values[offset]["openalex_id"]) in selected:
                offset += 1
            offsets[stratum] = offset + 1
            if offset >= len(values):
                continue
            row = values[offset]
            selected[str(row["openalex_id"])] = row
            progressed = True
            if len(selected) >= min(sample_size, len(candidates)):
                break
        if not progressed:
            break

    output: list[dict[str, Any]] = []
    for row in sorted(selected.values(), key=lambda item: _stable_rank(item, random_seed)):
        output.append(
            {
                "openalex_id": row.get("openalex_id"),
                "canonical_paper_id": row.get("canonical_paper_id"),
                "title": row.get("title"),
                "publication_year": row.get("publication_year"),
                "arxiv_id": row.get("arxiv_id"),
                "automatic_finance_status": row.get("finance_status"),
                "automatic_reasons": row.get("finance_audit_reasons", []),
                "matched_fields": _matched_fields(row.get("quant_match", {})),
                "matched_canonical_terms": sorted(_canonical_hits(row.get("quant_match", {}))),
                "review_strata": sorted(_strata(row)),
                "human_finance_status": None,
                "human_review_reason": "",
                "reviewer": "",
                "reviewed_at": None,
            }
        )
    return output


def evaluate_review_labels(
    rows: Iterable[Mapping[str, Any]], *, accepted_precision_threshold: float = 0.90
) -> dict[str, Any]:
    materialized = [dict(row) for row in rows]
    allowed = {"accepted", "review", "rejected"}
    unlabeled = [str(row.get("openalex_id") or "") for row in materialized if row.get("human_finance_status") not in allowed]
    automatic_accepted = [row for row in materialized if row.get("automatic_finance_status") == "accepted"]
    accepted_true_positive = sum(row.get("human_finance_status") == "accepted" for row in automatic_accepted)
    precision = accepted_true_positive / len(automatic_accepted) if automatic_accepted else 0.0
    confusion: Counter[str] = Counter(
        f"{row.get('automatic_finance_status')}->{row.get('human_finance_status')}"
        for row in materialized
        if row.get("human_finance_status") in allowed
    )
    complete = not unlabeled and bool(materialized)
    return {
        "schema_version": "openalex_gate2_label_evaluation_v1",
        "review_count": len(materialized),
        "labeled_count": len(materialized) - len(unlabeled),
        "unlabeled_count": len(unlabeled),
        "unlabeled_openalex_ids": unlabeled,
        "automatic_accepted_count": len(automatic_accepted),
        "automatic_accepted_true_positive_count": accepted_true_positive,
        "accepted_precision": round(precision, 6),
        "accepted_precision_threshold": accepted_precision_threshold,
        "confusion": dict(sorted(confusion.items())),
        "finance_review_status": (
            "passed" if complete and precision >= accepted_precision_threshold else
            "failed" if complete else
            "pending_manual_review"
        ),
    }


__all__ = [
    "FOCUS_TERMS",
    "build_gate2_summary",
    "build_stratified_review_sample",
    "evaluate_review_labels",
    "read_candidate_rows",
    "reaudit_row",
    "sha256_file",
]
