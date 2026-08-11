#!/usr/bin/env python3
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_THRESHOLDS_PATH = ROOT / "config" / "factor_quality_thresholds.yaml"


@lru_cache(maxsize=8)
def load_thresholds(path: str | Path = DEFAULT_THRESHOLDS_PATH) -> dict[str, Any]:
    threshold_path = Path(path)
    if not threshold_path.is_absolute():
        threshold_path = ROOT / threshold_path
    if not threshold_path.exists():
        return {"defaults": {}}
    payload = yaml.safe_load(threshold_path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {"defaults": {}}


def tier_thresholds(tier: str, path: str | Path = DEFAULT_THRESHOLDS_PATH) -> dict[str, Any]:
    payload = load_thresholds(path)
    defaults = payload.get("defaults", {}) if isinstance(payload.get("defaults"), dict) else {}
    tier_cfg = payload.get(tier, {}) if isinstance(payload.get(tier), dict) else {}
    merged = dict(defaults)
    merged.update(tier_cfg)
    return merged


def threshold_float(cfg: dict[str, Any], key: str, default: float) -> float:
    try:
        value = float(cfg.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def threshold_int(cfg: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def threshold_bool(cfg: dict[str, Any], key: str, default: bool) -> bool:
    value = cfg.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def direction_consistency(value: object, default: float = 0.5) -> float:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        numeric = default
    if not math.isfinite(numeric):
        numeric = default
    return max(numeric, 1.0 - numeric)


def metric_float(value: object, default: float = 0.0) -> float:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def metric_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def paper_hf_proxy_quality_label(metrics: dict[str, object], tier: str = "small", path: str | Path = DEFAULT_THRESHOLDS_PATH) -> dict[str, str]:
    mean_ic_raw = metrics.get("mean_daily_ic") if metrics.get("mean_daily_ic") is not None else metrics.get("mean_ic")
    try:
        mean_ic = float(mean_ic_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        mean_ic = math.nan
    tier_label = tier.lower()
    tier_text = tier_label.capitalize()
    cfg = tier_thresholds(tier_label, path)
    good_abs_ic = threshold_float(cfg, "good_abs_ic", threshold_float(cfg, "ic", 0.015))
    strong_abs_ic = threshold_float(cfg, "strong_abs_ic", max(good_abs_ic * 2, 0.030))
    if not math.isfinite(mean_ic):
        return {"label": f"weak({tier_label})", "class": "quality-weak", "reason": f"{tier_text} IC unavailable"}
    abs_ic = abs(mean_ic)
    if abs_ic > strong_abs_ic:
        if mean_ic < 0:
            return {"label": f"strong({tier_label}) negative alpha", "class": "quality-negative", "reason": f"{tier_text} IC {mean_ic:.4f}; |IC| > {strong_abs_ic:.3f}, can be inverted"}
        return {"label": f"strong({tier_label})", "class": "quality-strong", "reason": f"{tier_text} IC {mean_ic:.4f}; |IC| > {strong_abs_ic:.3f}"}
    if abs_ic > good_abs_ic:
        if mean_ic < 0:
            return {"label": f"good({tier_label}) negative alpha", "class": "quality-negative", "reason": f"{tier_text} IC {mean_ic:.4f}; |IC| > {good_abs_ic:.3f}, can be inverted"}
        return {"label": f"good({tier_label})", "class": "quality-good", "reason": f"{tier_text} IC {mean_ic:.4f}; |IC| > {good_abs_ic:.3f}"}
    if abs_ic > 0:
        return {"label": f"watch({tier_label})", "class": "quality-watch", "reason": f"{tier_text} |IC| {abs_ic:.4f} <= {good_abs_ic:.3f}"}
    return {"label": f"weak({tier_label})", "class": "quality-weak", "reason": f"{tier_text} IC is 0"}


def classify_factor_metrics(report: dict[str, object], tier: str = "small", path: str | Path = DEFAULT_THRESHOLDS_PATH) -> dict[str, object]:
    cfg = tier_thresholds(tier, path)
    min_obs = threshold_int(cfg, "min_obs", 1)
    finite_min = threshold_float(cfg, "finite_ratio", 0.95)
    zero_max = threshold_float(cfg, "zero_ratio", 0.30)
    min_ic = threshold_float(cfg, "ic", 0.01)
    min_rankic = threshold_float(cfg, "rank_ic", 0.01)
    min_qspread = threshold_float(cfg, "qspread", 0.50)
    min_ic_ir = threshold_float(cfg, "ic_ir", 0.25)
    min_rankic_ir = threshold_float(cfg, "rankic_ir", 0.25)
    min_qspread_ir = threshold_float(cfg, "qspread_ir", 0.25)
    min_direction = threshold_float(cfg, "direction_consistency", 0.65)
    min_abs_ic_ratio = threshold_float(cfg, "abs_ic_gt_002_ratio", 0.15)
    min_signal_rules = threshold_int(cfg, "signal_rule_min", 8)
    vote_margin = threshold_int(cfg, "vote_margin", 2)

    total_obs = metric_int(report.get("total_obs"), 0)
    mean_finite_ratio = metric_float(report.get("mean_finite_ratio"), 1.0)
    mean_zero_ratio = metric_float(report.get("mean_zero_ratio"), 0.0)
    mean_daily_ic = metric_float(report.get("mean_daily_ic"))
    mean_daily_rankic = metric_float(report.get("mean_daily_rankic"))
    mean_qspread = metric_float(report.get("mean_qspread"))
    ic_ir = metric_float(report.get("ic_ir"))
    rankic_ir = metric_float(report.get("rankic_ir"))
    qspread_ir = metric_float(report.get("qspread_ir"))
    positive_ic_ratio = metric_float(report.get("positive_ic_ratio"))
    positive_rankic_ratio = metric_float(report.get("positive_rankic_ratio"))
    positive_qspread_ratio = metric_float(report.get("positive_qspread_ratio"))
    abs_ic_gt_002_ratio = metric_float(report.get("abs_ic_gt_002_ratio"))
    ic_direction = direction_consistency(positive_ic_ratio)
    rankic_direction = direction_consistency(positive_rankic_ratio)
    qspread_direction = direction_consistency(positive_qspread_ratio)

    usable = total_obs >= min_obs and mean_finite_ratio >= finite_min and mean_zero_ratio <= zero_max
    report["usable"] = usable
    if not usable:
        report["classification"] = "failed_or_unusable"
        report["reason"] = f"未通过基础可用门槛 (Obs:{total_obs}>={min_obs}，有限值比例:{mean_finite_ratio:.2%}>={finite_min:.0%}，零值比例:{mean_zero_ratio:.2%}<={zero_max:.0%})"
        return report

    threshold_checks = [
        (abs(mean_daily_ic) >= min_ic, "IC", abs(mean_daily_ic), min_ic),
        (abs(mean_daily_rankic) >= min_rankic, "RankIC", abs(mean_daily_rankic), min_rankic),
        (abs(mean_qspread) >= min_qspread, "QSpread", abs(mean_qspread), min_qspread),
        (abs(ic_ir) >= min_ic_ir, "ICIR", abs(ic_ir), min_ic_ir),
        (abs(rankic_ir) >= min_rankic_ir, "RankICIR", abs(rankic_ir), min_rankic_ir),
        (abs(qspread_ir) >= min_qspread_ir, "QSpreadIR", abs(qspread_ir), min_qspread_ir),
    ]
    for passed, name, actual, required in threshold_checks:
        if not passed:
            report["classification"] = "usable_no_signal"
            report["reason"] = f"未通过 {name} 门槛 ({actual:.4f}<{required:.4f})"
            return report

    if min(ic_direction, rankic_direction, qspread_direction) < min_direction:
        report["classification"] = "mixed_direction"
        report["direction"] = "mixed"
        report["reason"] = f"未通过方向一致性门槛 (IC/RankIC/QSpread 任一方向一致性低于{min_direction:.0%})"
        return report

    signal_rules = [
        abs(mean_daily_ic) >= min_ic,
        abs(mean_daily_rankic) >= min_rankic,
        abs(mean_qspread) >= min_qspread,
        abs(ic_ir) >= min_ic_ir,
        abs(rankic_ir) >= min_rankic_ir,
        abs(qspread_ir) >= min_qspread_ir,
        abs_ic_gt_002_ratio >= min_abs_ic_ratio,
        ic_direction >= min_direction,
        rankic_direction >= min_direction,
        qspread_direction >= min_direction,
    ]
    signal_rule_count = sum(1 for rule in signal_rules if rule)
    signal_passed = signal_rule_count >= min_signal_rules
    report["signal_rule_count"] = signal_rule_count
    report["signal_passed"] = signal_passed
    if not signal_passed:
        report["classification"] = "usable_no_signal"
        report["reason"] = f"基础可用且核心门槛达标，但多维信号不足 (触发规则数: {signal_rule_count}/10，要求>={min_signal_rules})"
        return report

    positive_votes = sum([mean_daily_ic > 0, mean_daily_rankic > 0, mean_qspread > 0, positive_ic_ratio > 0.5, positive_rankic_ratio > 0.5, positive_qspread_ratio > 0.5])
    negative_votes = sum([mean_daily_ic < 0, mean_daily_rankic < 0, mean_qspread < 0, positive_ic_ratio < 0.5, positive_rankic_ratio < 0.5, positive_qspread_ratio < 0.5])
    report["positive_votes"] = positive_votes
    report["negative_votes"] = negative_votes
    if positive_votes >= negative_votes + vote_margin:
        report["classification"] = "positive_candidate"
        report["direction"] = "positive"
        report["good_computable_factor"] = True
        report["reason"] = f"正向有效因子候选 (净胜多头得票: {positive_votes - negative_votes})"
    elif negative_votes >= positive_votes + vote_margin:
        report["classification"] = "negative_candidate"
        report["direction"] = "negative"
        report["good_computable_factor"] = True
        report["reason"] = f"反向有效因子候选 (净胜空头得票: {negative_votes - positive_votes})"
    else:
        report["classification"] = "mixed_direction"
        report["direction"] = "mixed"
        report["good_computable_factor"] = False
        report["reason"] = f"信号显著但多空方向博弈严重 (正/负得票: {positive_votes}/{negative_votes})"
    return report


def candidate_score(summary: dict[str, Any]) -> float:
    return round(
        abs(metric_float(summary.get("mean_daily_ic"))) * 1000.0
        + abs(metric_float(summary.get("mean_daily_rankic"))) * 800.0
        + abs(metric_float(summary.get("mean_qspread"))) * 0.05
        + direction_consistency(summary.get("positive_ic_ratio")) * 0.5
        + direction_consistency(summary.get("positive_rankic_ratio")) * 0.4
        + direction_consistency(summary.get("positive_qspread_ratio")) * 0.3,
        6,
    )


def passes_candidate_tier(summary: dict[str, Any], tier: str = "medium", path: str | Path = DEFAULT_THRESHOLDS_PATH, cfg: dict[str, Any] | None = None) -> tuple[bool, bool, list[str]]:
    cfg = tier_thresholds(tier, path) if cfg is None else cfg
    reasons: list[str] = []
    min_obs = threshold_int(cfg, "min_obs", 1_000_000)
    finite_min = threshold_float(cfg, "finite_ratio", 0.90)
    zero_max = threshold_float(cfg, "zero_ratio", 0.70)
    min_ic = threshold_float(cfg, "ic", 0.0025)
    min_rankic = threshold_float(cfg, "rank_ic", 0.0025)
    min_qspread = threshold_float(cfg, "qspread", 0.10)
    min_direction = threshold_float(cfg, "direction_consistency", 0.60)
    min_abs_ic_gt_001 = threshold_float(cfg, "abs_ic_gt_001_ratio", 0.10)
    min_abs_ic_gt_002 = threshold_float(cfg, "abs_ic_gt_002_ratio", 0.03)
    relaxed_rule_min = threshold_int(cfg, "relaxed_rule_min", 2)
    good_abs_ic = threshold_float(cfg, "good_abs_ic", threshold_float(cfg, "ic", 0.015))
    force_good = threshold_bool(cfg, "force_small_good", True)

    total_obs = metric_int(summary.get("total_obs"), 0)
    finite = metric_float(summary.get("mean_finite_ratio"), 0.0)
    zero = metric_float(summary.get("mean_zero_ratio"), 1.0)
    mean_ic = metric_float(summary.get("mean_daily_ic"))
    mean_rankic = metric_float(summary.get("mean_daily_rankic"))
    mean_qspread = metric_float(summary.get("mean_qspread"))
    max_direction = max(direction_consistency(summary.get("positive_ic_ratio")), direction_consistency(summary.get("positive_rankic_ratio")), direction_consistency(summary.get("positive_qspread_ratio")))
    abs_ic_gt_001 = metric_float(summary.get("abs_ic_gt_001_ratio"))
    abs_ic_gt_002 = metric_float(summary.get("abs_ic_gt_002_ratio"))
    tier_good = abs(mean_ic) > good_abs_ic

    if total_obs < min_obs:
        return False, False, [f"Obs<{min_obs}"]
    if finite < finite_min:
        return False, False, [f"Finite<{finite_min:.0%}"]
    if zero > zero_max:
        return False, False, [f"Zero>{zero_max:.0%}"]
    if tier_good:
        reasons.append(f"{tier}-good |Mean IC|>{good_abs_ic:.3f}")
    if abs(mean_ic) >= min_ic:
        reasons.append(f"|Mean IC|>={min_ic:.4f}")
    if abs(mean_rankic) >= min_rankic:
        reasons.append(f"|Mean RankIC|>={min_rankic:.4f}")
    if abs(mean_qspread) >= min_qspread:
        reasons.append(f"|Mean QSpread|>={min_qspread:.4f}")
    if max_direction >= min_direction:
        reasons.append(f"direction consistency>={min_direction:.0%}")
    if abs_ic_gt_001 >= min_abs_ic_gt_001:
        reasons.append(f"|IC|>0.01 rows>={min_abs_ic_gt_001:.0%}")
    if abs_ic_gt_002 >= min_abs_ic_gt_002:
        reasons.append(f"|IC|>0.02 rows>={min_abs_ic_gt_002:.0%}")
    return (force_good and tier_good) or len(reasons) >= relaxed_rule_min, tier_good, reasons