#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.factor.core.normalization import normalize_paper_hf_factors  # noqa: E402
from src.factor.evaluation.quality_rules import passes_candidate_tier  # noqa: E402

START_MARKER = "<!-- HF_PROXY_DIVERSITY_SUMMARY_START -->"
END_MARKER = "<!-- HF_PROXY_DIVERSITY_SUMMARY_END -->"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _result_field_count(path: Path) -> int:
    payload = _load_json(path)
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return -1
    return len({str(row.get("factor_field") or "") for row in rows if isinstance(row, dict) and row.get("factor_field")})


def _result_fields(path: Path) -> set[str]:
    payload = _load_json(path)
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return set()
    return {str(row.get("factor_field") or "") for row in rows if isinstance(row, dict) and row.get("factor_field")}


def _manifest_fields(path: Path) -> set[str]:
    payload = _load_json(path)
    specs = payload.get("specs", []) if isinstance(payload, dict) else []
    if not isinstance(specs, list):
        return set()
    return {str(item.get("field") or "") for item in specs if isinstance(item, dict) and item.get("field")}


def _default_small_result_path() -> Path:
    data_dir = ROOT / "data"
    current_fields = _manifest_fields(data_dir / "paper_hf_factor_tests_v2" / "manifest.json")
    candidates = [
        path
        for path in [
            *sorted((data_dir / "runtime").glob("render_small_union*/paper_hf_direct_proxy_tests_v2.json")),
            *sorted((data_dir / "guarded_paper_hf_runs").glob("*/results/small1_final_split/paper_hf_direct_proxy_tests_v2.json")),
            *sorted((data_dir / "guarded_paper_hf_runs").glob("*/results/small1/paper_hf_direct_proxy_tests_v2.json")),
            data_dir / "paper_hf_factor_results_small1" / "paper_hf_direct_proxy_tests_v2.json",
            data_dir / "paper_hf_factor_results_v2" / "paper_hf_direct_proxy_tests_v2.json",
        ]
        if path.exists()
    ]
    if not candidates:
        return data_dir / "paper_hf_factor_results_v2" / "paper_hf_direct_proxy_tests_v2.json"
    if current_fields:
        return max(candidates, key=lambda path: (len(_result_fields(path) & current_fields), -len(_result_fields(path) - current_fields), path.stat().st_mtime))
    return max(candidates, key=lambda path: (_result_field_count(path), path.stat().st_mtime))


def _extra_manifest_specs(primary_manifest_path: Path) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    manifest_paths = [
        path
        for path in sorted((ROOT / "data" / "guarded_paper_hf_runs").glob("*/factors_delta/manifest.json"))
        if path != primary_manifest_path and path.exists()
    ]
    for path in manifest_paths:
        payload = _load_json(path)
        specs.extend(item for item in payload.get("specs", []) if isinstance(item, dict))
    return specs


def _extra_small_result_paths(primary_small_result_path: Path) -> list[Path]:
    paths = [
        path
        for path in sorted((ROOT / "data" / "guarded_paper_hf_runs").glob("*/results/small1/paper_hf_direct_proxy_tests_v2.json"))
        if path.exists() and path.resolve() != primary_small_result_path.resolve()
    ]
    return paths


def _load_small_rows_with_extras(primary_small_result_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    included_paths: list[str] = []

    def add_rows(path: Path) -> None:
        payload = _load_json(path)
        added = 0
        for row in payload.get("rows", []) if isinstance(payload, dict) else []:
            if not isinstance(row, dict):
                continue
            field = str(row.get("factor_field") or "")
            if not field:
                continue
            key = (field, str(row.get("code") or ""), str(row.get("horizon") or ""), str(row.get("segment") or ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            added += 1
        if added:
            included_paths.append(str(path))

    add_rows(primary_small_result_path)
    if os.environ.get("PAPER_HF_INCLUDE_EXTRA_SMALL_RESULTS") == "1":
        for path in _extra_small_result_paths(primary_small_result_path):
            add_rows(path)
    return rows, included_paths


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _field_summaries(rows: list[dict[str, Any]], horizon: str | None = None) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if horizon is not None and str(row.get("horizon") or "") != horizon:
            continue
        if isinstance(row, dict) and row.get("factor_field"):
            grouped[str(row["factor_field"])].append(row)
    out: dict[str, dict[str, Any]] = {}
    for field, field_rows in grouped.items():
        daily_ic = [_safe_float(row.get("daily_ic")) for row in field_rows]
        rankic = [_safe_float(row.get("daily_rankic")) for row in field_rows]
        qspread = [_safe_float(row.get("qspread_mean")) for row in field_rows]
        finite = [_safe_float(row.get("finite_ratio"), 0.0) for row in field_rows]
        zero = [_safe_float(row.get("zero_ratio"), 1.0) for row in field_rows]
        out[field] = {
            "row_count": len(field_rows),
            "total_obs": int(sum(int(row.get("n_obs") or 0) for row in field_rows)),
            "mean_daily_ic": round(sum(daily_ic) / len(daily_ic), 6) if daily_ic else None,
            "mean_daily_rankic": round(sum(rankic) / len(rankic), 6) if rankic else None,
            "mean_qspread": round(sum(qspread) / len(qspread), 6) if qspread else None,
            "mean_finite_ratio": round(sum(finite) / len(finite), 6) if finite else None,
            "mean_zero_ratio": round(sum(zero) / len(zero), 6) if zero else None,
        }
    return out


FIDELITY_SCORE = {
    "high": 100.0,
    "medium_high": 85.0,
    "medium": 65.0,
    "low_medium": 45.0,
    "low": 25.0,
    "unknown": 35.0,
}
STATUS_SCORE = {
    "fully_computable": 100.0,
    "partially_computable": 60.0,
    "unsupported": 10.0,
    "unmapped": 0.0,
    "unknown": 25.0,
}
STRENGTH_SCORE = {
    "direct": 100.0,
    "derived": 85.0,
    "weak_proxy": 45.0,
    "future_pipeline": 15.0,
    "unsupported": 0.0,
}


def _mean(values: list[float], default: float = 0.0) -> float:
    return sum(values) / len(values) if values else default


def _proxy_reliability_summary(specs: list[dict[str, Any]]) -> dict[str, Any]:
    if not specs:
        return {
            "proxy_reliability_score": 0.0,
            "avg_confidence": None,
            "executable_ratio": None,
            "reviewed_ratio": None,
            "direct_derived_ratio": None,
            "unresolved_per_spec": None,
        }
    fidelity_scores = [FIDELITY_SCORE.get(str(spec.get("proxy_fidelity") or "unknown"), 35.0) for spec in specs]
    status_scores: list[float] = []
    confidences: list[float] = []
    executable = 0
    reviewed = 0
    direct_derived = 0
    mapping_count = 0
    unresolved_count = 0
    for spec in specs:
        factor = spec.get("paper_hf_factor") if isinstance(spec.get("paper_hf_factor"), dict) else {}
        status_scores.append(STATUS_SCORE.get(str(factor.get("proxy_status") or "unknown"), 25.0))
        unresolved = factor.get("unresolved_proxy_variables") if isinstance(factor.get("unresolved_proxy_variables"), list) else []
        unresolved_count += len(unresolved)
        mappings = factor.get("proxy_mappings") if isinstance(factor.get("proxy_mappings"), list) else []
        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue
            mapping_count += 1
            confidence = mapping.get("confidence")
            if confidence is not None:
                confidences.append(_safe_float(confidence))
            if str(mapping.get("validation_status") or "") == "executable":
                executable += 1
            if str(mapping.get("review_status") or "") == "reviewed":
                reviewed += 1
            if str(mapping.get("proxy_strength") or "") in {"direct", "derived"}:
                direct_derived += 1
    executable_ratio = executable / mapping_count if mapping_count else None
    reviewed_ratio = reviewed / mapping_count if mapping_count else None
    direct_derived_ratio = direct_derived / mapping_count if mapping_count else None
    unresolved_per_spec = unresolved_count / len(specs)
    score = (
        0.25 * _mean(fidelity_scores)
        + 0.20 * _mean(status_scores)
        + 0.20 * (_mean(confidences, 0.35) * 100.0)
        + 0.15 * ((executable_ratio if executable_ratio is not None else 0.0) * 100.0)
        + 0.10 * ((reviewed_ratio if reviewed_ratio is not None else 0.0) * 100.0)
        + 0.10 * ((direct_derived_ratio if direct_derived_ratio is not None else 0.0) * 100.0)
    )
    score = max(0.0, score - min(unresolved_per_spec * 6.0, 35.0))
    return {
        "proxy_reliability_score": round(score, 1),
        "avg_confidence": round(_mean(confidences), 4) if confidences else None,
        "mapping_count": mapping_count,
        "executable_ratio": round(executable_ratio, 6) if executable_ratio is not None else None,
        "reviewed_ratio": round(reviewed_ratio, 6) if reviewed_ratio is not None else None,
        "direct_derived_ratio": round(direct_derived_ratio, 6) if direct_derived_ratio is not None else None,
        "unresolved_per_spec": round(unresolved_per_spec, 6),
    }


def _template_utility_rows(specs_by_field: dict[str, dict[str, Any]], tier_rows: dict[str, list[dict[str, Any]]], *, group_key: str) -> list[dict[str, Any]]:
    tier_summaries = {tier: _field_summaries(rows, horizon="ret60s") for tier, rows in tier_rows.items()}
    grouped_fields: dict[str, set[str]] = defaultdict(set)
    for field, spec in specs_by_field.items():
        key = str(spec.get(group_key) or "unknown")
        grouped_fields[key].add(field)

    rows: list[dict[str, Any]] = []
    for key, fields in grouped_fields.items():
        group_specs = [specs_by_field[field] for field in fields if field in specs_by_field]
        reliability = _proxy_reliability_summary(group_specs)
        tier_stats: dict[str, dict[str, Any]] = {}
        for tier, summaries in tier_summaries.items():
            values = [
                _safe_float(summaries[field].get("mean_daily_ic"))
                for field in fields
                if field in summaries and summaries[field].get("mean_daily_ic") is not None
            ]
            tier_stats[tier] = {
                "count": len(values),
                "mean_abs_ic": round(sum(abs(value) for value in values) / len(values), 6) if values else None,
                "mean_ic": round(sum(values) / len(values), 6) if values else None,
                "abs_ic_gt_002_ratio": round(sum(1 for value in values if abs(value) > 0.02) / len(values), 6) if values else None,
                "direction_consistency": round(abs(sum(1 if value > 0 else -1 if value < 0 else 0 for value in values)) / len(values), 6) if values else None,
            }
        small = tier_stats.get("small", {})
        medium = tier_stats.get("medium", {})
        large = tier_stats.get("large", {})
        small_count = int(small.get("count") or 0)
        small_abs = small.get("mean_abs_ic")
        medium_abs = medium.get("mean_abs_ic")
        large_abs = large.get("mean_abs_ic")
        keep_score = max(
            [value for value in (small_abs, medium_abs, large_abs) if isinstance(value, (int, float))] or [0.0]
        )
        validation_bonus = 0.0
        if isinstance(medium_abs, (int, float)):
            validation_bonus += min(medium_abs / 0.03, 1.0)
        if isinstance(large_abs, (int, float)):
            validation_bonus += min(large_abs / 0.03, 1.0)
        utility_score = round(
            100.0
            * (
                0.45 * min((_safe_float(small.get("mean_abs_ic")) / 0.03), 1.0)
                + 0.25 * _safe_float(small.get("abs_ic_gt_002_ratio"))
                + 0.20 * min(validation_bonus / 2.0, 1.0)
                + 0.10 * _safe_float(small.get("direction_consistency"))
            ),
            1,
        )
        reliability_score = _safe_float(reliability.get("proxy_reliability_score"))
        combined_score = round(0.75 * utility_score + 0.25 * reliability_score, 1)
        medium_count = int(medium.get("count") or 0)
        large_count = int(large.get("count") or 0)
        validation_count = medium_count + large_count
        if key.startswith("unmapped"):
            recommendation = "map-before-action"
        elif reliability_score < 40 and small_count >= 20:
            recommendation = "proxy-review"
        elif small_count >= 20 and keep_score < 0.006:
            recommendation = "trim"
        elif small_count >= 20 and utility_score < 18:
            recommendation = "trim"
        elif small_count >= 20 and utility_score < 35:
            recommendation = "base-only"
        elif validation_count > 0 and utility_score >= 55:
            recommendation = "keep"
        elif validation_count > 0 and utility_score >= 35:
            recommendation = "validate-more"
        elif small_count >= 10 and keep_score < 0.02:
            recommendation = "base-only"
        else:
            recommendation = "probe"
        rows.append(
            {
                "key": key,
                "generated": len(fields),
                "small": small,
                "medium": medium,
                "large": large,
                "utility_score": utility_score,
                "proxy_reliability_score": reliability_score,
                "combined_score": combined_score,
                "proxy_reliability": reliability,
                "recommendation": recommendation,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            _safe_float(row.get("combined_score")),
            _safe_float(row.get("utility_score")),
            int(row["large"].get("count") or 0) > 0,
            int(row["medium"].get("count") or 0) > 0,
            _safe_float(row["small"].get("mean_abs_ic")),
            int(row.get("generated") or 0),
        ),
        reverse=True,
    )


def _queued_weak_proxy_fields() -> set[str]:
    fields: set[str] = set()
    for state_name in (
        "weak_proxy_small_backtest_state.json",
        "candidate_templates_small_backtest_state.json",
        "abstract_weak_proxy_small_backtest_state.json",
    ):
        state_path = ROOT / "data" / "runtime" / state_name
        if not state_path.exists():
            continue
        payload = _load_json(state_path)
        fields.update(str(item) for item in payload.get("fields", []) if str(item))
    return fields


def _weak_proxy_template_ids() -> set[str]:
    config = _load_yaml(ROOT / "config" / "proxy_variant_templates.yaml")
    ids: set[str] = set()
    for item in config.get("templates", []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        template_id = str(item.get("id"))
        if item.get("base_only") or template_id.startswith("paper_hf_abstract_"):
            ids.add(template_id)
    return ids


def _count_with_ratio(count: int, denom: int) -> str:
    if denom <= 0:
        return f"{count} / NA"
    return f"{count} / {denom} ({count / denom:.1%})"


PLACEHOLDER_FORMULA_RE = re.compile(r"(待\s*LLM|启发式|unknown|待补|todo|n/a|未提供|缺失)", re.I)
BULK_COMPOSITE_STATE_PATH = ROOT / "data" / "bulk_composite_factor_synthesis_state.json"


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _has_custom_formula(factor: dict[str, Any]) -> bool:
    plan = factor.get("paper_hf_formula_plan")
    if not isinstance(plan, dict):
        return False
    formula = str(plan.get("custom_formula") or "").strip()
    return bool(formula) and not PLACEHOLDER_FORMULA_RE.search(formula)


def _paper_factors_for_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_paper_hf_factors(row.get("paper_hf_factors") or [])


def _formula_readiness_summary(latest_path: Path) -> dict[str, int]:
    total = 0
    formula_ready = 0
    for row in _iter_jsonl(latest_path):
        for factor in _paper_factors_for_row(row):
            if not isinstance(factor, dict):
                continue
            total += 1
            if _has_custom_formula(factor):
                formula_ready += 1
    return {
        "paper_hf_factor_rows_total": total,
        "formula_ready_paper_hf_factors": formula_ready,
        "placeholder_paper_hf_factors": max(total - formula_ready, 0),
    }


def _formula_coverage_summary(latest_path: Path, specs: list[dict[str, Any]]) -> dict[str, int]:
    covered_keys: set[tuple[str, str]] = set()
    for item in specs:
        row_key = str(item.get("row_url") or item.get("row_title") or "")
        raw_index = item.get("paper_hf_factor_index")
        if raw_index is None:
            covered_keys.add((row_key, ""))
            continue
        covered_keys.add((row_key, str(raw_index)))
        if str(raw_index) == "0":
            covered_keys.add((row_key, ""))

    total = 0
    formula_ready = 0
    generated = 0
    known_factor_ids: set[str] = set()
    formula_ready_ids: set[str] = set()
    for row_index, row in enumerate(_iter_jsonl(latest_path)):
        row_key = str(row.get("url") or row.get("title") or "")
        dedup_key = str(row.get("dedup_key") or f"row_{row_index}")
        for factor_index, factor in enumerate(_paper_factors_for_row(row)):
            if not isinstance(factor, dict):
                continue
            total += 1
            hf_factor_id = f"{dedup_key}:{factor_index}"
            known_factor_ids.add(hf_factor_id)
            if not _has_custom_formula(factor):
                continue
            formula_ready += 1
            formula_ready_ids.add(hf_factor_id)
            if (row_key, str(factor_index)) in covered_keys:
                generated += 1
    attempted_ids: set[str] = set()
    if BULK_COMPOSITE_STATE_PATH.exists():
        try:
            state = json.loads(BULK_COMPOSITE_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
        if isinstance(state, dict):
            attempted_ids = {str(item) for item in state.get("attempted_missing_formula_hf_factor_ids", []) if str(item)} & known_factor_ids
    baseline_formula_ready = formula_ready
    if BULK_COMPOSITE_STATE_PATH.exists():
        try:
            baseline_formula_ready = int(state.get("formula_ready_baseline", formula_ready)) if isinstance(state, dict) else formula_ready
        except (TypeError, ValueError):
            baseline_formula_ready = formula_ready
    coverage_total = baseline_formula_ready + len(attempted_ids)
    return {
        "paper_hf_factor_rows_total": total,
        "formula_ready_paper_hf_factors": formula_ready,
        "formula_ready_paper_hf_factors_generated": generated,
        "formula_coverage_paper_hf_factors": coverage_total,
        "formula_ready_baseline_paper_hf_factors": baseline_formula_ready,
        "bulk_composite_tested_paper_hf_factors": len(attempted_ids),
        "placeholder_paper_hf_factors": max(total - coverage_total, 0),
    }


def _classify_unresolved(raw_variable: str) -> str:
    lowered = raw_variable.lower()
    if "," in raw_variable or "，" in raw_variable:
        return "复合变量列表"
    if re.search(r"[+*/=<>Σ∑]|\bsum\b|\bmax\b|\bmin\b|sqrt|log|corr|rolling", lowered):
        return "公式片段/运算符"
    if re.search(r"_t$|_[itkcs]$|\{.*\}|\^|\d", raw_variable):
        return "数学符号下标"
    if any(term in lowered for term in ("timestamp", "series", "state", "side", "threshold", "horizon", "window")):
        return "通用数据维度"
    if len(raw_variable.strip()) <= 4:
        return "短词歧义"
    if any(term in lowered for term in ("wti", "brent", "eps", "earnings", "consensus", "announcement")):
        return "外部/事件数据"
    return "需新增注册规则或别名"


def _proxy_registry_summary(registry_path: Path, audit_path: Path) -> dict[str, Any]:
    registry = _load_yaml(registry_path)
    variables = registry.get("variables", {}) if isinstance(registry, dict) else {}
    if not isinstance(variables, dict):
        variables = {}
    families = []
    strength_counts: Counter[str] = Counter()
    review_counts: Counter[str] = Counter()
    for family, meta in sorted(variables.items()):
        if not isinstance(meta, dict):
            meta = {}
        strength = str(meta.get("proxy_strength") or "unknown")
        review_status = str(meta.get("review_status") or "unknown")
        strength_counts[strength] += 1
        review_counts[review_status] += 1
        families.append({"family": family, "proxy_strength": strength, "review_status": review_status})
    audit = _load_json(audit_path)
    unresolved = [item for item in audit.get("unresolved_variables", []) if isinstance(item, dict)]
    unresolved_reason_counts: Counter[str] = Counter()
    unresolved_examples: dict[str, str] = {}
    for item in unresolved:
        raw_variable = str(item.get("raw_variable") or "")
        reason = _classify_unresolved(raw_variable)
        unresolved_reason_counts[reason] += 1
        unresolved_examples.setdefault(reason, raw_variable)
    suggestions = [item for item in audit.get("family_suggestions", []) if isinstance(item, dict)]
    return {
        "registry_family_count": len(families),
        "registry_families": families,
        "registry_strength_counts": dict(strength_counts),
        "registry_review_counts": dict(review_counts),
        "suggested_family_count": len(suggestions),
        "suggested_families": [str(item.get("suggested_family")) for item in suggestions if item.get("suggested_family")],
        "unresolved_unique_variables": int(audit.get("summary", {}).get("unresolved_unique_variables") or len(unresolved)),
        "unresolved_reason_counts": dict(unresolved_reason_counts),
        "unresolved_reason_examples": unresolved_examples,
    }


def _registry_family_usage_rows(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    field_counts: Counter[str] = Counter()
    mechanism_keys: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for spec in specs:
        if not isinstance(spec, dict) or not spec.get("field"):
            continue
        factor = spec.get("paper_hf_factor") if isinstance(spec.get("paper_hf_factor"), dict) else {}
        mappings = factor.get("proxy_mappings") if isinstance(factor.get("proxy_mappings"), list) else []
        row_key = str(spec.get("row_url") or spec.get("row_title") or "")
        factor_index = str(spec.get("paper_hf_factor_index") if spec.get("paper_hf_factor_index") is not None else "")
        families_for_spec: set[str] = set()
        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue
            family = str(mapping.get("canonical_variable") or mapping.get("family") or mapping.get("variable_family") or "").strip()
            if family:
                families_for_spec.add(family)
        for family in families_for_spec:
            field_counts[family] += 1
            if row_key or factor_index:
                mechanism_keys[family].add((row_key, factor_index))
    rows = [
        {"family": family, "generated_fields": count, "mechanisms": len(mechanism_keys.get(family, set()))}
        for family, count in field_counts.items()
    ]
    return sorted(rows, key=lambda item: (int(item["generated_fields"]), int(item["mechanisms"]), str(item["family"])), reverse=True)


def build_summary(manifest_path: Path, small_result_path: Path, medium_report_path: Path, medium_result_path: Path, large_result_path: Path, registry_path: Path, audit_path: Path, latest_path: Path) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    specs = [item for item in manifest.get("specs", []) if isinstance(item, dict)]
    specs_by_field = {str(item.get("field")): item for item in specs if item.get("field")}
    utility_specs_by_field = dict(specs_by_field)
    for item in _extra_manifest_specs(manifest_path):
        if item.get("field"):
            utility_specs_by_field.setdefault(str(item.get("field")), item)
    small_rows, included_small_result_paths = _load_small_rows_with_extras(small_result_path)
    small_summaries = _field_summaries(small_rows)
    small_fields = set(small_summaries)
    current_fields = set(specs_by_field)
    current_small_fields = small_fields & current_fields
    stale_small_fields = small_fields - current_fields
    all_small_mapped_fields = small_fields & set(utility_specs_by_field)
    all_small_unmapped_fields = small_fields - set(utility_specs_by_field)
    utility_specs_with_unmapped = dict(utility_specs_by_field)
    for field in all_small_unmapped_fields:
        utility_specs_with_unmapped[field] = {
            "field": field,
            "template": "unmapped_small_result",
            "variant_transform": "unmapped",
            "proxy_fidelity": "unknown",
        }

    medium_report = _load_json(medium_report_path)
    medium_selected = [item for item in medium_report.get("selected", []) if isinstance(item, dict)]
    medium_selected_fields = {str(item.get("field")) for item in medium_selected if item.get("field")}
    if not medium_selected_fields:
        medium_selected_fields = {str(field) for field in medium_report.get("selected_fields", []) if field}
    medium_payload = _load_json(medium_result_path)
    medium_rows = [row for row in medium_payload.get("rows", []) if isinstance(row, dict)]
    medium_fields = set(_field_summaries(medium_rows))
    large_payload = _load_json(large_result_path)
    large_rows = [row for row in large_payload.get("rows", []) if isinstance(row, dict)]
    large_fields = set(_field_summaries(large_rows))

    transform_counts = Counter(str(item.get("variant_transform") or "unknown") for item in specs)
    fidelity_counts = Counter(str(item.get("proxy_fidelity") or "unknown") for item in specs)
    template_counts = Counter(str(item.get("template") or "unknown") for item in specs)
    current_small_transform_counts = Counter(str(specs_by_field[field].get("variant_transform") or "unknown") for field in current_small_fields if field in specs_by_field)
    current_small_fidelity_counts = Counter(str(specs_by_field[field].get("proxy_fidelity") or "unknown") for field in current_small_fields if field in specs_by_field)
    current_small_template_counts = Counter(str(specs_by_field[field].get("template") or "unknown") for field in current_small_fields if field in specs_by_field)
    small_pass_fields = {
        field
        for field, metrics in small_summaries.items()
        if field in specs_by_field and passes_candidate_tier(metrics, "small", ROOT / "config/factor_quality_thresholds.yaml")[0]
    }
    small_pass_transform_counts = Counter(str(specs_by_field[field].get("variant_transform") or "unknown") for field in small_pass_fields)
    small_pass_fidelity_counts = Counter(str(specs_by_field[field].get("proxy_fidelity") or "unknown") for field in small_pass_fields)

    factor_keys = {
        (str(item.get("row_url") or item.get("row_title") or ""), str(item.get("paper_hf_factor_index") or ""))
        for item in specs
    }
    paper_keys = {key[0] for key in factor_keys if key[0]}
    small_factor_keys = {
        (str(specs_by_field[field].get("row_url") or specs_by_field[field].get("row_title") or ""), str(specs_by_field[field].get("paper_hf_factor_index") or ""))
        for field in current_small_fields
        if field in specs_by_field
    }
    small_pass_factor_keys = {
        (str(specs_by_field[field].get("row_url") or specs_by_field[field].get("row_title") or ""), str(specs_by_field[field].get("paper_hf_factor_index") or ""))
        for field in small_pass_fields
        if field in specs_by_field
    }
    small_pass_paper_keys = {key[0] for key in small_pass_factor_keys if key[0]}

    duplicate_groups = {template: count for template, count in template_counts.items() if count > 1}
    top_templates = template_counts.most_common(12)
    top_current_small_templates = current_small_template_counts.most_common(12)
    registry_family_usage_rows = _registry_family_usage_rows(specs)
    utility_tier_rows = {"small": small_rows, "medium": medium_rows, "large": large_rows}
    transform_utility_rows = _template_utility_rows(utility_specs_with_unmapped, utility_tier_rows, group_key="variant_transform")
    template_utility_rows = _template_utility_rows(utility_specs_with_unmapped, utility_tier_rows, group_key="template")
    weak_template_ids = _weak_proxy_template_ids()
    weak_specs = [item for item in specs if str(item.get("template") or "") in weak_template_ids]
    weak_fields = {str(item.get("field")) for item in weak_specs if item.get("field")}
    weak_small_fields = weak_fields & current_small_fields
    weak_pass_fields = weak_fields & small_pass_fields
    weak_queued_fields = weak_fields & _queued_weak_proxy_fields()
    weak_factor_keys = {
        (str(item.get("row_url") or item.get("row_title") or ""), str(item.get("paper_hf_factor_index") or ""))
        for item in weak_specs
    }
    weak_template_counts = Counter(str(item.get("template") or "unknown") for item in weak_specs)
    weak_small_template_counts = Counter(str(specs_by_field[field].get("template") or "unknown") for field in weak_small_fields if field in specs_by_field)
    transform_rows = []
    for transform, count in transform_counts.most_common():
        transform_rows.append(
            {
                "transform": transform,
                "generated": count,
                "small_current": current_small_transform_counts.get(transform, 0),
                "small_pass": small_pass_transform_counts.get(transform, 0),
            }
        )
    fidelity_rows = []
    for fidelity, count in fidelity_counts.most_common():
        fidelity_rows.append(
            {
                "proxy_fidelity": fidelity,
                "generated": count,
                "small_current": current_small_fidelity_counts.get(fidelity, 0),
                "small_pass": small_pass_fidelity_counts.get(fidelity, 0),
            }
        )

    selected_current = medium_selected_fields & current_fields
    selected_stale = medium_selected_fields - current_fields
    formula_summary = _formula_coverage_summary(latest_path, specs)
    formula_ready_count = int(formula_summary.get("formula_ready_paper_hf_factors") or 0)
    formula_ready_generated = int(formula_summary.get("formula_ready_paper_hf_factors_generated") or 0)
    formula_coverage_total = int(formula_summary.get("formula_coverage_paper_hf_factors") or formula_ready_count)
    analysis_rows = _iter_jsonl(latest_path)
    article_pool_count = len(analysis_rows)
    article_pool_v6_count = sum(1 for row in analysis_rows if ("schema-v6" in str(row.get("analysis_agent", ""))) or ("schema-v3" in str(row.get("analysis_agent", ""))))
    article_pool_v2_count = sum(1 for row in analysis_rows if str(row.get("analysis_version", "")) == "v2")
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": str(manifest_path),
        "latest_path": str(latest_path),
        "small_result_path": str(small_result_path),
        "included_small_result_paths": included_small_result_paths,
        "medium_report_path": str(medium_report_path),
        "medium_result_path": str(medium_result_path),
        "large_result_path": str(large_result_path),
        "generated_fields": len(current_fields),
        "article_pool_count": article_pool_count,
        "generated_specs": len(specs),
        "generated_templates": len(template_counts),
        "duplicate_template_groups": len(duplicate_groups),
        "small_result_fields": len(small_fields),
        "small_current_fields": len(current_small_fields),
        "all_small_mapped_fields": len(all_small_mapped_fields),
        "all_small_unmapped_fields": len(all_small_unmapped_fields),
        "utility_manifest_fields": len(utility_specs_by_field),
        "utility_scored_fields": len(utility_specs_with_unmapped),
        "small_pass_fields": len(small_pass_fields),
        "small_missing_current_fields": len(current_fields - small_fields),
        "medium_current_fields": len(current_fields & medium_fields),
        "medium_missing_current_fields": len(current_fields - medium_fields),
        "large_current_fields": len(current_fields & large_fields),
        "large_missing_current_fields": len(current_fields - large_fields),
        "small_stale_fields": len(stale_small_fields),
        "unique_paper_hf_factors_generated": len(factor_keys),
        "formula_ready_paper_hf_factors": formula_ready_count,
        "formula_ready_paper_hf_factors_generated": formula_ready_generated,
        "formula_coverage_paper_hf_factors": formula_coverage_total,
        "formula_ready_baseline_paper_hf_factors": formula_summary.get("formula_ready_baseline_paper_hf_factors", formula_ready_count),
        "bulk_composite_tested_paper_hf_factors": formula_summary.get("bulk_composite_tested_paper_hf_factors", 0),
        "paper_hf_factor_rows_total": formula_summary.get("paper_hf_factor_rows_total", 0),
        "placeholder_paper_hf_factors": formula_summary.get("placeholder_paper_hf_factors", 0),
        "unique_paper_hf_factors_with_small": len(small_factor_keys),
        "unique_paper_hf_factors_with_small_pass": len(small_pass_factor_keys),
        "unique_papers_generated": len(paper_keys),
        "unique_papers_with_small_pass": len(small_pass_paper_keys),
        "medium_selected_fields": len(medium_selected_fields),
        "medium_selected_current_fields": len(selected_current),
        "medium_selected_stale_fields": len(selected_stale),
        "medium_eval_fields": len(medium_fields),
        "large_eval_fields": len(large_fields),
        "transform_rows": transform_rows,
        "fidelity_rows": fidelity_rows,
        "top_templates": top_templates,
        "top_current_small_templates": top_current_small_templates,
        "registry_family_usage_rows": registry_family_usage_rows,
        "transform_utility_rows": transform_utility_rows,
        "template_utility_rows": template_utility_rows,
        "weak_proxy_exploratory": {
            "field_count": len(weak_fields),
            "mechanism_count": len(weak_factor_keys),
            "small_current_fields": len(weak_small_fields),
            "small_pass_fields": len(weak_pass_fields),
            "queued_fields": len(weak_queued_fields - weak_small_fields),
            "missing_unqueued_fields": len(weak_fields - current_small_fields - weak_queued_fields),
            "template_counts": weak_template_counts.most_common(20),
            "small_template_counts": weak_small_template_counts.most_common(20),
        },
    }
    summary.update(_proxy_registry_summary(registry_path, audit_path))
    return summary


def render_html(summary: dict[str, Any]) -> str:
    esc = lambda value: html.escape(str(value), quote=True)
    def metric_cell(payload: object, key: str) -> str:
        if not isinstance(payload, dict) or payload.get(key) is None:
            return "-"
        value = _safe_float(payload.get(key))
        if key.endswith("ratio"):
            return f"{value:.1%}"
        return f"{value:.4f}"

    def utility_table(rows: list[dict[str, Any]], limit: int = 24) -> str:
        body = "".join(
            "<tr>"
            f"<td><code>{esc(row.get('key'))}</code></td>"
            f"<td>{metric_cell(row, 'combined_score')}</td>"
            f"<td>{metric_cell(row, 'utility_score')}</td>"
            f"<td>{metric_cell(row, 'proxy_reliability_score')}</td>"
            f"<td>{int(row.get('generated') or 0)}</td>"
            f"<td>{int(row.get('small', {}).get('count') or 0)}</td>"
            f"<td>{metric_cell(row.get('small'), 'mean_abs_ic')}</td>"
            f"<td>{metric_cell(row.get('small'), 'abs_ic_gt_002_ratio')}</td>"
            f"<td>{metric_cell(row.get('small'), 'direction_consistency')}</td>"
            f"<td>{metric_cell(row.get('proxy_reliability'), 'avg_confidence')}</td>"
            f"<td>{metric_cell(row.get('proxy_reliability'), 'executable_ratio')}</td>"
            f"<td>{metric_cell(row.get('proxy_reliability'), 'direct_derived_ratio')}</td>"
            f"<td>{metric_cell(row.get('proxy_reliability'), 'unresolved_per_spec')}</td>"
            f"<td>{int(row.get('medium', {}).get('count') or 0)}</td>"
            f"<td>{metric_cell(row.get('medium'), 'mean_abs_ic')}</td>"
            f"<td>{int(row.get('large', {}).get('count') or 0)}</td>"
            f"<td>{metric_cell(row.get('large'), 'mean_abs_ic')}</td>"
            f"<td>{esc(row.get('recommendation'))}</td>"
            "</tr>"
            for row in rows[:limit]
        )
        return body or '<tr><td colspan="18">暂无 ret60s 回测数据。</td></tr>'

    transform_rows = "".join(
        f"<tr><td>{esc(row['transform'])}</td><td>{row['generated']}</td><td>{row['small_current']}</td><td>{row.get('small_pass', 0)}</td></tr>"
        for row in summary.get("transform_rows", [])
    )
    fidelity_rows = "".join(
        f"<tr><td>{esc(row['proxy_fidelity'])}</td><td>{row['generated']}</td><td>{row['small_current']}</td><td>{row.get('small_pass', 0)}</td></tr>"
        for row in summary.get("fidelity_rows", [])
    )
    top_templates = "".join(
        f"<tr><td><code>{esc(name)}</code></td><td>{count}</td></tr>"
        for name, count in summary.get("top_templates", [])
    )
    top_current_small_templates = "".join(
        f"<tr><td><code>{esc(name)}</code></td><td>{count}</td></tr>"
        for name, count in summary.get("top_current_small_templates", [])
    ) or '<tr><td colspan="2">当前 788 版 small eval 尚未完成或尚无交集。</td></tr>'
    weak_summary = summary.get("weak_proxy_exploratory", {}) if isinstance(summary.get("weak_proxy_exploratory"), dict) else {}
    weak_template_rows = "".join(
        f"<tr><td><code>{esc(name)}</code></td><td>{count}</td></tr>"
        for name, count in weak_summary.get("template_counts", [])
    ) or '<tr><td colspan="2">暂无探索性 weak proxy 字段。</td></tr>'
    weak_small_template_rows = "".join(
        f"<tr><td><code>{esc(name)}</code></td><td>{count}</td></tr>"
        for name, count in weak_summary.get("small_template_counts", [])
    ) or '<tr><td colspan="2">探索性 weak proxy small 尚未完成。</td></tr>'
    transform_utility_rows = utility_table([row for row in summary.get("transform_utility_rows", []) if isinstance(row, dict)], limit=20)
    template_utility_rows = utility_table([row for row in summary.get("template_utility_rows", []) if isinstance(row, dict)], limit=30)
    strength_rows = "".join(
        f"<tr><td>{esc(name)}</td><td>{count}</td></tr>"
        for name, count in sorted(summary.get("registry_strength_counts", {}).items())
    )
    review_rows = "".join(
        f"<tr><td>{esc(name)}</td><td>{count}</td></tr>"
        for name, count in sorted(summary.get("registry_review_counts", {}).items())
    )
    family_rows = "".join(
        f"<tr><td><code>{esc(item.get('family'))}</code></td><td>{int(item.get('generated_fields') or 0)}</td><td>{int(item.get('mechanisms') or 0)}</td><td>{esc(item.get('proxy_strength'))}</td><td>{esc(item.get('review_status'))}</td></tr>"
        for item in summary.get("registry_families", [])
    )
    family_usage_by_name = {
        str(item.get("family")): item
        for item in summary.get("registry_family_usage_rows", [])
        if isinstance(item, dict) and item.get("family")
    }
    family_rows = "".join(
        f"<tr><td><code>{esc(item.get('family'))}</code></td><td>{int(family_usage_by_name.get(str(item.get('family')), {}).get('generated_fields') or 0)}</td><td>{int(family_usage_by_name.get(str(item.get('family')), {}).get('mechanisms') or 0)}</td><td>{esc(item.get('proxy_strength'))}</td><td>{esc(item.get('review_status'))}</td></tr>"
        for item in summary.get("registry_families", [])
    )
    family_usage_rows = "".join(
        f"<tr><td><code>{esc(item.get('family'))}</code></td><td>{int(item.get('generated_fields') or 0)}</td><td>{int(item.get('mechanisms') or 0)}</td></tr>"
        for item in summary.get("registry_family_usage_rows", [])[:20]
    ) or '<tr><td colspan="3">暂无 registry family 使用记录。</td></tr>'
    unresolved_rows = "".join(
        f"<tr><td>{esc(reason)}</td><td>{count}</td><td><code>{esc(summary.get('unresolved_reason_examples', {}).get(reason, ''))}</code></td></tr>"
        for reason, count in sorted(summary.get("unresolved_reason_counts", {}).items(), key=lambda item: item[1], reverse=True)
    )
    suggested_families = "".join(f"<span class=\"factor-chip\">{esc(name)}</span>" for name in summary.get("suggested_families", []))
    generated = int(summary.get("generated_fields") or 0)
    article_pool_count = int(summary.get("article_pool_count") or 0)
    article_pool_v6_count = int(summary.get("article_pool_v6_count") or 0)
    article_pool_v2_count = int(summary.get("article_pool_v2_count") or 0)
    small_current = int(summary.get("small_current_fields") or 0)
    small_result_fields = int(summary.get("small_result_fields") or 0)
    all_small_mapped = int(summary.get("all_small_mapped_fields") or 0)
    all_small_unmapped = int(summary.get("all_small_unmapped_fields") or 0)
    utility_manifest_fields = int(summary.get("utility_manifest_fields") or 0)
    utility_scored_fields = int(summary.get("utility_scored_fields") or 0)
    small_pass = int(summary.get("small_pass_fields") or 0)
    small_missing = int(summary.get("small_missing_current_fields") or 0)
    medium_current_fields = int(summary.get("medium_current_fields") or 0)
    medium_missing_current_fields = int(summary.get("medium_missing_current_fields") or 0)
    large_current_fields = int(summary.get("large_current_fields") or 0)
    large_missing_current_fields = int(summary.get("large_missing_current_fields") or 0)
    medium_selected = int(summary.get("medium_selected_fields") or 0)
    medium_current = int(summary.get("medium_selected_current_fields") or 0)
    medium_eval = int(summary.get("medium_eval_fields") or 0)
    large_eval = int(summary.get("large_eval_fields") or 0)
    formula_ready = int(summary.get("formula_ready_paper_hf_factors") or 0)
    formula_ready_generated = int(summary.get("formula_ready_paper_hf_factors_generated") or 0)
    formula_coverage_total = int(summary.get("formula_coverage_paper_hf_factors") or formula_ready)
    bulk_tested = int(summary.get("bulk_composite_tested_paper_hf_factors") or 0)
    total_hf_rows = int(summary.get("paper_hf_factor_rows_total") or 0)
    placeholder_hf = int(summary.get("placeholder_paper_hf_factors") or 0)
    weak_fields = int(weak_summary.get("field_count") or 0)
    weak_mechanisms = int(weak_summary.get("mechanism_count") or 0)
    weak_small_current = int(weak_summary.get("small_current_fields") or 0)
    weak_small_pass = int(weak_summary.get("small_pass_fields") or 0)
    weak_queued = int(weak_summary.get("queued_fields") or 0)
    weak_missing_unqueued = int(weak_summary.get("missing_unqueued_fields") or 0)
    return f"""
<section class="dashboard" id="hf-proxy-diversity-summary">
  <div class="dashboard-head">
    <div>
      <h2>HF Proxy 去重与同质化摘要</h2>
    <div class="dashboard-note">用于判断代理变体是否集中在少数模板/transform 上；small 主覆盖口径使用 all-small 回测与当前/增量 manifest 的可映射字段，当前 manifest 直接交集仅作为字段漂移诊断。</div>
    </div>
    <div class="dashboard-note">生成时间：{esc(summary.get('generated_at', ''))}</div>
  </div>
  <div class="stat-grid">
    <div class="stat-card"><div class="stat-label">稳定文章池</div><div class="stat-value">{article_pool_count}</div><div class="stat-sub">当前已解析 arXiv 文章总数</div></div>
    <div class="stat-card"><div class="stat-label">明确公式 HF</div><div class="stat-value">{formula_ready}</div><div class="stat-sub">严格来自 custom_formula；非 custom {placeholder_hf}</div></div>
    <div class="stat-card"><div class="stat-label">明确公式代理覆盖</div><div class="stat-value">{formula_ready_generated} / {formula_ready}</div><div class="stat-sub">LLM 已测试 {bulk_tested}；{_count_with_ratio(formula_ready_generated, formula_ready)}</div></div>
    <div class="stat-card"><div class="stat-label">当前可计算代理字段</div><div class="stat-value">{generated}</div><div class="stat-sub">模板 {summary.get('generated_templates')} 组；重复模板 {summary.get('duplicate_template_groups')} 组</div></div>
    <div class="stat-card"><div class="stat-label">功效评分字段池</div><div class="stat-value">{utility_scored_fields}</div><div class="stat-sub">manifest 映射 {utility_manifest_fields}；含 unmapped small 组</div></div>
    <div class="stat-card"><div class="stat-label">当前 medium 已覆盖</div><div class="stat-value">{medium_current_fields}</div><div class="stat-sub">{_count_with_ratio(medium_current_fields, generated)}；未覆盖 {medium_missing_current_fields}</div></div>
    <div class="stat-card"><div class="stat-label">当前 large 已覆盖</div><div class="stat-value">{large_current_fields}</div><div class="stat-sub">{_count_with_ratio(large_current_fields, generated)}；未覆盖 {large_missing_current_fields}</div></div>
        <div class="stat-card"><div class="stat-label">small 通过字段</div><div class="stat-value">{small_pass}</div><div class="stat-sub">{_count_with_ratio(small_pass, generated)}</div></div>
        <div class="stat-card"><div class="stat-label">全量 HF 因子进度</div><div class="stat-value">{summary.get('unique_paper_hf_factors_generated')}</div><div class="stat-sub">{_count_with_ratio(int(summary.get('unique_paper_hf_factors_generated') or 0), total_hf_rows)}；small 通过 {summary.get('unique_paper_hf_factors_with_small_pass')}</div></div>
    <div class="stat-card"><div class="stat-label">medium 入选字段</div><div class="stat-value">{medium_selected}</div><div class="stat-sub">其中属于当前 788 版：{medium_current}</div></div>
    <div class="stat-card"><div class="stat-label">medium 分布字段</div><div class="stat-value">{medium_eval}</div><div class="stat-sub">用于首页 Medium IC 分布/方向统计</div></div>
    <div class="stat-card"><div class="stat-label">large 已评估字段</div><div class="stat-value">{large_eval}</div><div class="stat-sub">当前 HF promoted candidates large 仍待复检</div></div>
  </div>
    <div class="dashboard-note">探索性 weak proxy 单独统计：这些字段只使用本地 tick/book/return 数据构造低保真代理，不等同于论文公式复现。</div>
    <div class="stat-grid">
        <div class="stat-card"><div class="stat-label">探索性 weak proxy</div><div class="stat-value">{weak_fields}</div><div class="stat-sub">覆盖机制 {weak_mechanisms}</div></div>
        <div class="stat-card"><div class="stat-label">weak small 已完成</div><div class="stat-value">{weak_small_current}</div><div class="stat-sub">{_count_with_ratio(weak_small_current, weak_fields)}</div></div>
        <div class="stat-card"><div class="stat-label">weak small 通过</div><div class="stat-value">{weak_small_pass}</div><div class="stat-sub">{_count_with_ratio(weak_small_pass, weak_fields)}</div></div>
        <div class="stat-card"><div class="stat-label">weak small 已排队</div><div class="stat-value">{weak_queued}</div><div class="stat-sub">未排队 {weak_missing_unqueued}</div></div>
    </div>
  <div class="threshold-grid">
    <div class="threshold-card"><strong>旧 small 结果字段</strong><span>{summary.get('small_stale_fields')}</span></div>
    <div class="threshold-card"><strong>medium 旧版入选</strong><span>{summary.get('medium_selected_stale_fields')}</span></div>
    <div class="threshold-card"><strong>medium eval 字段</strong><span>{summary.get('medium_eval_fields')}</span></div>
    <div class="threshold-card"><strong>生成 specs</strong><span>{summary.get('generated_specs')}</span></div>
    <div class="threshold-card"><strong>custom_formula 总数</strong><span>{formula_ready}</span></div>
    <div class="threshold-card"><strong>全量 HF 行数</strong><span>{total_hf_rows}</span></div>
    <div class="threshold-card"><strong>待补机制公式</strong><span>{placeholder_hf}</span></div>
  </div>
  <div class="factor-detail-grid">
    <div class="factor-detail"><strong>Transform 字段分布</strong><table><thead><tr><th>transform</th><th>生成字段</th><th>当前 small 覆盖字段</th><th>small 通过字段</th></tr></thead><tbody>{transform_rows}</tbody></table></div>
    <div class="factor-detail"><strong>Proxy Fidelity 字段分布</strong><table><thead><tr><th>fidelity</th><th>生成字段</th><th>当前 small 覆盖字段</th><th>small 通过字段</th></tr></thead><tbody>{fidelity_rows}</tbody></table></div>
    <div class="factor-detail"><strong>生成数最多的模板</strong><table><thead><tr><th>template</th><th>字段数</th></tr></thead><tbody>{top_templates}</tbody></table></div>
    <div class="factor-detail"><strong>当前 small 覆盖模板</strong><table><thead><tr><th>template</th><th>字段数</th></tr></thead><tbody>{top_current_small_templates}</tbody></table></div>
    <div class="factor-detail"><strong>Registry Family 使用频率 Top</strong><table><thead><tr><th>family</th><th>生成字段</th><th>原始因子</th></tr></thead><tbody>{family_usage_rows}</tbody></table></div>
    <div class="factor-detail"><strong>探索性 weak proxy 模板</strong><table><thead><tr><th>template</th><th>字段数</th></tr></thead><tbody>{weak_template_rows}</tbody></table></div>
    <div class="factor-detail"><strong>weak proxy small 覆盖模板</strong><table><thead><tr><th>template</th><th>字段数</th></tr></thead><tbody>{weak_small_template_rows}</tbody></table></div>
        <div class="factor-detail"><strong>结论</strong><p>主覆盖口径为严格 custom_formula paper_hf_factor：当前可生成代理 {formula_ready_generated} / {formula_ready}。Transform/Fidelity/Template 分区均为代理字段口径，同一个原始因子会生成多个字段，因此不能与原始因子总数直接相加比较。</p></div>
  </div>
    <div class="dashboard-note">模板/窗口裁剪建议：以下均按 all-small ret60s 的 daily IC 统计；可映射字段 {all_small_mapped} / {small_result_fields}。score=综合分；bt=回测功效分；proxy=本地代理可靠分。生成数/small数只表示样本覆盖，不作为加分项。建议含义：keep=保留默认；validate-more=候选但需继续复验；base-only=不要继续扩展该变换；trim=裁剪；proxy-review=先审代理可靠性；map-before-action=先补模板映射。</div>
    <div class="factor-detail-grid utility-grid">
        <div class="factor-detail"><strong>Transform / 窗口实用性</strong><table><thead><tr><th>transform</th><th>score</th><th>bt</th><th>proxy</th><th>生成</th><th>small</th><th>small |IC|</th><th>small |IC|&gt;.02</th><th>方向一致</th><th>conf</th><th>exec</th><th>direct/derived</th><th>unresolved</th><th>medium</th><th>medium |IC|</th><th>large</th><th>large |IC|</th><th>建议</th></tr></thead><tbody>{transform_utility_rows}</tbody></table></div>
        <div class="factor-detail"><strong>Template 实用性 Top</strong><table><thead><tr><th>template</th><th>score</th><th>bt</th><th>proxy</th><th>生成</th><th>small</th><th>small |IC|</th><th>small |IC|&gt;.02</th><th>方向一致</th><th>conf</th><th>exec</th><th>direct/derived</th><th>unresolved</th><th>medium</th><th>medium |IC|</th><th>large</th><th>large |IC|</th><th>建议</th></tr></thead><tbody>{template_utility_rows}</tbody></table></div>
        <div class="factor-detail"><strong>Registry Family 明细</strong><table><thead><tr><th>family</th><th>生成字段</th><th>原始因子</th><th>proxy_strength</th><th>review</th></tr></thead><tbody>{family_rows}</tbody></table></div>
    </div>
</section>
""".strip()


def inject_dashboard(index_path: Path, block: str) -> None:
    text = index_path.read_text(encoding="utf-8")
    wrapped = f"{START_MARKER}\n{block}\n{END_MARKER}"
    if START_MARKER in text and END_MARKER in text:
        pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.S)
        text = pattern.sub(wrapped, text)
    else:
        anchor = '<div class="paper-search" aria-label="Paper search">'
        if anchor not in text:
            raise RuntimeError(f"dashboard anchor not found in {index_path}")
        text = text.replace(anchor, wrapped + "\n        " + anchor, 1)
    index_path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize HF proxy diversity and inject a dashboard block.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/paper_hf_factor_tests_v2/manifest.json")
    parser.add_argument("--small-result", type=Path, default=_default_small_result_path())
    parser.add_argument("--medium-report", type=Path, default=ROOT / "reports/paper_hf_medium_candidates.json")
    parser.add_argument("--medium-result", type=Path, default=ROOT / "data/paper_hf_factor_results_medium1/paper_hf_direct_proxy_tests_v2.json")
    parser.add_argument("--large-result", type=Path, default=ROOT / "data/factor_results_large1_selected_final/paper_hf_relaxed_medium_candidates.json")
    parser.add_argument("--registry", type=Path, default=ROOT / "config/proxy_registry.yaml")
    parser.add_argument("--audit", type=Path, default=ROOT / "data/proxy_variable_audit.json")
    parser.add_argument("--latest", type=Path, default=ROOT / "data/analysis_archive.jsonl")
    parser.add_argument("--json-out", type=Path, default=ROOT / "reports/hf_proxy_diversity_summary.json")
    parser.add_argument("--html-out", type=Path, default=ROOT / "reports/hf_proxy_diversity_summary.html")
    parser.add_argument("--dashboard", type=Path, default=ROOT / "public/index.html")
    parser.add_argument("--no-inject", action="store_true")
    args = parser.parse_args()

    summary = build_summary(args.manifest, args.small_result, args.medium_report, args.medium_result, args.large_result, args.registry, args.audit, args.latest)
    html_block = render_html(summary)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.html_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    args.html_out.write_text(html_block + "\n", encoding="utf-8")
    if not args.no_inject:
        inject_dashboard(args.dashboard, html_block)
    print(json.dumps({
        "status": "ok",
        "generated_fields": summary["generated_fields"],
        "small_result_fields": summary["small_result_fields"],
        "small_current_fields": summary["small_current_fields"],
        "all_small_mapped_fields": summary["all_small_mapped_fields"],
        "all_small_unmapped_fields": summary["all_small_unmapped_fields"],
        "small_missing_current_fields": summary["small_missing_current_fields"],
        "medium_selected_fields": summary["medium_selected_fields"],
        "large_eval_fields": summary["large_eval_fields"],
        "registry_family_count": summary["registry_family_count"],
        "unresolved_unique_variables": summary["unresolved_unique_variables"],
        "dashboard": str(args.dashboard),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
