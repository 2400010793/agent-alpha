from __future__ import annotations


def _float_or_none(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if result != result:
        return None
    return result


def _rankic(metrics: dict) -> float:
    for key in ("daily_rankic", "global_rankic", "rankic", "daily_ic", "global_ic"):
        value = _float_or_none(metrics.get(key))
        if value is not None:
            return value
    return 0.0


def analyze_risk(metrics: dict, config: dict | None = None) -> dict:
    config = config or {}
    finite_ratio = _float_or_none(metrics.get("finite_ratio"))
    zero_ratio = _float_or_none(metrics.get("zero_ratio"))
    n_obs = _float_or_none(metrics.get("n_obs"))
    abs_rankic = abs(_rankic(metrics))
    min_finite_ratio = float(config.get("min_finite_ratio", 0.8))
    max_zero_ratio = float(config.get("max_zero_ratio", 0.95))
    min_n_obs = float(config.get("min_n_obs", 1000))

    risk_flags: list[str] = []
    if zero_ratio is not None and zero_ratio > max_zero_ratio:
        risk_flags.append("zero_ratio_too_high")
    if finite_ratio is not None and finite_ratio < min_finite_ratio:
        risk_flags.append("finite_ratio_too_low")
    if n_obs is not None and n_obs < min_n_obs:
        risk_flags.append("n_obs_too_low")
    if n_obs is not None and n_obs < min_n_obs and abs_rankic >= float(config.get("min_abs_rankic", 0.02)):
        risk_flags.append("rankic_sample_fragile")

    summary = "risk checks passed" if not risk_flags else ", ".join(risk_flags)
    return {"ok": not risk_flags, "risk_flags": risk_flags, "summary": summary}