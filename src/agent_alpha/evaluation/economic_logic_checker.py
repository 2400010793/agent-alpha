from __future__ import annotations


def check_economic_logic(candidate: dict, source_signal: dict | None = None) -> dict:
    source_signal = source_signal or {}
    rationale = str(
        candidate.get("economic_rationale")
        or source_signal.get("market_intuition")
        or source_signal.get("hypothesis")
        or ""
    ).strip()
    mechanism_tags = candidate.get("mechanism_tags") or candidate.get("hf_mechanism_tags") or source_signal.get("mechanism_tags") or source_signal.get("hf_mechanism_tags") or []
    direction = str(candidate.get("direction") or candidate.get("expected_direction") or source_signal.get("expected_direction") or "").strip()

    missing: list[str] = []
    if not rationale:
        missing.append("economic_rationale")
    if not mechanism_tags:
        missing.append("mechanism_tags")
    if not direction or direction == "unknown":
        missing.append("direction")
    ok = not missing
    reason = "ok" if ok else "missing " + ", ".join(missing)
    summary = rationale if rationale else reason
    if mechanism_tags:
        summary += f"; mechanisms={','.join(str(tag) for tag in mechanism_tags)}"
    if direction and direction != "unknown":
        summary += f"; direction={direction}"
    return {"ok": ok, "reason": reason, "summary": summary}