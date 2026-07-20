from __future__ import annotations


def rank_signals(signals: list[dict]) -> list[dict]:
    """Rank generated signals by simple local evidence and implementability cues."""

    def score(signal: dict) -> tuple[int, int, int, int, int]:
        evidence_score = len(signal.get("evidence_ids", []) if isinstance(signal.get("evidence_ids"), list) else [])
        field_score = len(signal.get("candidate_fields", []) if isinstance(signal.get("candidate_fields"), list) else [])
        tag_score = len(signal.get("hf_mechanism_tags", []) if isinstance(signal.get("hf_mechanism_tags"), list) else [])
        intuition_score = 1 if str(signal.get("market_intuition") or "").strip() else 0
        hypothesis_score = 1 if str(signal.get("hypothesis") or "").strip() else 0
        return (evidence_score, field_score, tag_score, intuition_score, hypothesis_score)

    return sorted(signals, key=score, reverse=True)