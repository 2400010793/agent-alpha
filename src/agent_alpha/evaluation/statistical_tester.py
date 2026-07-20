from __future__ import annotations


def _float_or_none(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if result != result:
        return None
    return result


def _first_float(metrics: dict, names: tuple[str, ...]) -> float | None:
    for name in names:
        value = _float_or_none(metrics.get(name))
        if value is not None:
            return value
    return None


def test_statistical_strength(metrics: dict, config: dict) -> dict:
    rankic_value = _first_float(metrics, ("daily_rankic", "global_rankic", "rankic", "daily_ic", "global_ic"))
    finite_ratio = _first_float(metrics, ("finite_ratio",))
    zero_ratio = _first_float(metrics, ("zero_ratio",))
    qspread_mean = _first_float(metrics, ("qspread_mean",))
    abs_rankic = abs(rankic_value or 0.0)
    min_abs_rankic = float(config.get("min_abs_rankic", 0.02))
    min_finite_ratio = float(config.get("min_finite_ratio", 0.8))
    max_zero_ratio = float(config.get("max_zero_ratio", 0.95))

    reasons: list[str] = []
    if rankic_value is None:
        reasons.append("missing_rankic")
    elif abs_rankic < min_abs_rankic:
        reasons.append(f"rankic_too_weak:{abs_rankic:g}<{min_abs_rankic:g}")
    if finite_ratio is None:
        reasons.append("missing_finite_ratio")
    elif finite_ratio < min_finite_ratio:
        reasons.append(f"finite_ratio_too_low:{finite_ratio:g}<{min_finite_ratio:g}")
    if zero_ratio is None:
        reasons.append("missing_zero_ratio")
    elif zero_ratio > max_zero_ratio:
        reasons.append(f"zero_ratio_too_high:{zero_ratio:g}>{max_zero_ratio:g}")

    ok = not reasons
    summary = (
        f"rankic={rankic_value if rankic_value is not None else 'missing'}, "
        f"abs_rankic={abs_rankic:g}, finite_ratio={finite_ratio if finite_ratio is not None else 'missing'}, "
        f"zero_ratio={zero_ratio if zero_ratio is not None else 'missing'}"
    )
    if qspread_mean is not None:
        summary += f", qspread_mean={qspread_mean:g}"
    summary += "; statistical thresholds passed" if ok else "; " + ", ".join(reasons)
    return {
        "ok": ok,
        "rankic_value": rankic_value,
        "abs_rankic": abs_rankic,
        "finite_ratio": finite_ratio,
        "zero_ratio": zero_ratio,
        "qspread_mean": qspread_mean,
        "reasons": reasons,
        "summary": summary,
    }