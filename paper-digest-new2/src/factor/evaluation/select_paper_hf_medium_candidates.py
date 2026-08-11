#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from src.factor.evaluation.quality_rules import DEFAULT_THRESHOLDS_PATH, candidate_score, direction_consistency, passes_candidate_tier, threshold_int, tier_thresholds
except ImportError:  # pragma: no cover - supports package-style imports in tests/tools
    from src.factor.evaluation.quality_rules import DEFAULT_THRESHOLDS_PATH, candidate_score, direction_consistency, passes_candidate_tier, threshold_int, tier_thresholds


ROOT = Path(__file__).resolve().parents[2]


def _load_factor_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("paper_hf_factor_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load factor file: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _finite_float(value: object, default: float = 0.0) -> float:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _ratio(values: list[float], predicate) -> float | None:
    return round(sum(1 for value in values if predicate(value)) / len(values), 6) if values else None


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def values(name: str) -> list[float]:
        out: list[float] = []
        for row in rows:
            value = row.get(name)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                out.append(float(value))
        return out

    daily_ic = values("daily_ic")
    rankic = values("daily_rankic")
    qspread = values("qspread_mean")
    finite = values("finite_ratio")
    zero = values("zero_ratio")
    total_obs = 0
    for row in rows:
        try:
            total_obs += int(row.get("n_obs") or 0)
        except (TypeError, ValueError):
            pass
    return {
        "row_count": len(rows),
        "total_obs": total_obs,
        "mean_daily_ic": _mean(daily_ic),
        "mean_daily_rankic": _mean(rankic),
        "mean_qspread": _mean(qspread),
        "positive_ic_ratio": _ratio(daily_ic, lambda value: value > 0),
        "positive_rankic_ratio": _ratio(rankic, lambda value: value > 0),
        "positive_qspread_ratio": _ratio(qspread, lambda value: value > 0),
        "mean_finite_ratio": _mean(finite),
        "mean_zero_ratio": _mean(zero),
        "ic_gt_001_ratio": _ratio(daily_ic, lambda value: value > 0.01),
        "abs_ic_gt_001_ratio": _ratio(daily_ic, lambda value: abs(value) > 0.01),
        "abs_ic_gt_0015_ratio": _ratio(daily_ic, lambda value: abs(value) > 0.015),
        "abs_ic_gt_002_ratio": _ratio(daily_ic, lambda value: abs(value) > 0.02),
    }


def _direction_consistency(ratio: object) -> float:
    return direction_consistency(ratio)


def _candidate_score(summary: dict[str, Any]) -> float:
    return candidate_score(summary)


def _passes_relaxed(summary: dict[str, Any], cfg: dict[str, Any], tier: str) -> tuple[bool, bool, list[str]]:
    return passes_candidate_tier(summary, tier=tier, cfg=cfg)


def _safe_name(value: str, limit: int = 48) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_").lower()
    return (cleaned or "paper_hf")[:limit]


FIDELITY_RANK = {
    "high": 5,
    "medium_high": 4,
    "medium": 3,
    "low_medium": 2,
    "low": 1,
}

TRANSFORM_RANK = {
    "base": 6,
    "original": 6,
    "direct": 6,
    "L1_depth": 5,
    "L5_depth": 5,
    "L10_depth": 5,
    "zscore_120": 4,
    "rolling_window_20": 3,
    "normalized_60": 3,
    "direction_flip": 1,
}


def _hf_factor_key(metadata: dict[str, Any], field: str) -> str:
    paper_key = str(metadata.get("row_url") or metadata.get("row_title") or "").strip()
    factor_index = str(metadata.get("paper_hf_factor_index") if metadata.get("paper_hf_factor_index") is not None else "").strip()
    if paper_key or factor_index:
        return f"{paper_key}#{factor_index}"
    return f"field:{field}"


def _group_sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, str]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
    fidelity = str(metadata.get("proxy_fidelity") or "").lower()
    transform = str(metadata.get("variant_transform") or "").lower()
    finite_ratio = _finite_float(summary.get("mean_finite_ratio"), 0.0)
    zero_ratio = _finite_float(summary.get("mean_zero_ratio"), 1.0)
    return (
        1.0 if item.get("small_good") else 0.0,
        _finite_float(item.get("score"), 0.0),
        float(FIDELITY_RANK.get(fidelity, 0)),
        float(TRANSFORM_RANK.get(transform, 0)) + finite_ratio - zero_ratio,
        str(item.get("field") or ""),
    )


def _cap_per_hf_factor(selected: list[dict[str, Any]], max_per_hf_factor: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    if max_per_hf_factor <= 0:
        return selected, [], {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        field = str(item.get("field") or "")
        item["hf_factor_key"] = _hf_factor_key(metadata, field)
        grouped[str(item["hf_factor_key"])].append(item)

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    group_sizes: dict[str, int] = {}
    for key, items in grouped.items():
        ranked = sorted(items, key=_group_sort_key, reverse=True)
        group_sizes[key] = len(ranked)
        for idx, item in enumerate(ranked, start=1):
            item["hf_factor_group_rank"] = idx
            item["hf_factor_group_size"] = len(ranked)
            item["hf_factor_group_cap"] = max_per_hf_factor
            if idx <= max_per_hf_factor:
                kept.append(item)
            else:
                dropped.append(item)
    kept.sort(key=lambda item: item["score"], reverse=True)
    dropped.sort(key=lambda item: item["score"], reverse=True)
    return kept, dropped, group_sizes


def _render_selected_factor_file(source_text: str, fields: list[str], selected_metadata: list[dict[str, Any]], dedup_key: str) -> str:
    start = source_text.index("def compute_factor")
    prefix = source_text[:start]
    lines = source_text[start:].splitlines()
    selected = set(fields)
    body_lines = [
        "def compute_factor(code: str, date: str, df: pd.DataFrame) -> pd.DataFrame:",
        "    del code, date",
        "    out = pd.DataFrame(index=df.index)",
    ]
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("out["):
            try:
                field = stripped.split("out[", 1)[1].split("]", 1)[0]
                field = json.loads(field)
            except Exception:
                continue
            if field in selected:
                body_lines.append(line)
    body_lines.append("    return out.reset_index(drop=True)")
    metadata = {
        "dedup_key": dedup_key,
        "source": "paper_hf_factors_medium_candidates",
        "generation_method": "paper_hf_relaxed_medium_selection_v1",
        "factor_count": len(fields),
        "factors": selected_metadata,
    }
    return prefix + f"FACTOR_METADATA = {metadata!r}\n\n" + "fields = " + repr(fields) + "\n\n" + "\n".join(body_lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Select relaxed paper_hf V2 candidates and render a medium-eval factor file.")
    parser.add_argument("--factor-file", default="data/paper_hf_factor_tests_v2/paper_hf_direct_proxy_tests_v2.py")
    parser.add_argument("--result-json", default="data/paper_hf_factor_results_v2/paper_hf_direct_proxy_tests_v2.json")
    parser.add_argument("--output-dir", default="data/promoted_factors")
    parser.add_argument("--report", default="reports/paper_hf_medium_candidates.json")
    parser.add_argument("--dedup-key", default="paper_hf_relaxed_medium_candidates")
    parser.add_argument("--thresholds", default=str(DEFAULT_THRESHOLDS_PATH))
    parser.add_argument("--tier", default="medium", choices=("small", "medium", "large"))
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--min-obs", type=int, default=None)
    parser.add_argument("--good-abs-ic-threshold", type=float, default=None)
    parser.add_argument("--max-per-hf-factor", type=int, default=None, help="Keep at most this many proxy variants per original paper_hf_factor; 0 disables the cap.")
    parser.add_argument("--dry-run", action="store_true", help="Only print selection counts; do not write reports or promoted factor files.")
    args = parser.parse_args()

    threshold_cfg = tier_thresholds(args.tier, args.thresholds)
    if args.min_obs is not None:
        threshold_cfg["min_obs"] = args.min_obs
    if args.good_abs_ic_threshold is not None:
        threshold_cfg["good_abs_ic"] = args.good_abs_ic_threshold
    top_k = args.top_k if args.top_k is not None else threshold_int(threshold_cfg, "top_k_extra", 20)
    max_per_hf_factor = args.max_per_hf_factor if args.max_per_hf_factor is not None else threshold_int(threshold_cfg, "max_per_hf_factor", 0)

    factor_file = (ROOT / args.factor_file).resolve()
    result_json = (ROOT / args.result_json).resolve()
    output_dir = (ROOT / args.output_dir).resolve()
    report_path = (ROOT / args.report).resolve()

    module = _load_factor_module(factor_file)
    factor_metadata = getattr(module, "FACTOR_METADATA", {})
    metadata_by_field = {
        str(item.get("field")): item
        for item in factor_metadata.get("factors", [])
        if isinstance(item, dict) and item.get("field")
    }

    payload = json.loads(result_json.read_text(encoding="utf-8"))
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    rows_by_field: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        field = str(row.get("factor_field") or "")
        if field:
            rows_by_field.setdefault(field, []).append(row)

    candidates: list[dict[str, Any]] = []
    for field, field_rows in rows_by_field.items():
        summary = _summarize(field_rows)
        passed, small_good, reasons = _passes_relaxed(summary, threshold_cfg, args.tier)
        metadata = metadata_by_field.get(field, {})
        item = {
            "field": field,
            "selected": passed,
            "small_good": small_good,
            "selection_tier": args.tier,
            "selection_reasons": reasons,
            "score": _candidate_score(summary),
            "summary": summary,
            "metadata": metadata,
        }
        candidates.append(item)

    selected = [item for item in candidates if item["selected"]]
    selected.sort(key=lambda item: item["score"], reverse=True)
    forced_good = [item for item in selected if item.get("small_good")]
    relaxed_extra = [item for item in selected if not item.get("small_good")]
    if top_k > 0:
        remaining_slots = max(0, top_k - len(forced_good))
        selected = forced_good + relaxed_extra[:remaining_slots]
    else:
        selected = forced_good + relaxed_extra
    selected_before_group_cap = list(selected)
    selected, dropped_by_group_cap, group_sizes = _cap_per_hf_factor(selected, max_per_hf_factor)
    selected_fields = [str(item["field"]) for item in selected]
    selected_metadata = [
        {
            **dict(item.get("metadata") or {}),
            "selection_score": item["score"],
            "selection_reasons": item["selection_reasons"],
            "small_eval_summary": item["summary"],
            "hf_factor_key": item.get("hf_factor_key"),
            "hf_factor_group_rank": item.get("hf_factor_group_rank"),
            "hf_factor_group_size": item.get("hf_factor_group_size"),
            "hf_factor_group_cap": item.get("hf_factor_group_cap"),
        }
        for item in selected
    ]

    selected_factor_path = output_dir / f"{_safe_name(args.dedup_key)}.py"
    selected_meta_path = output_dir / f"{_safe_name(args.dedup_key)}.json"
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        source_text = factor_file.read_text(encoding="utf-8")
        selected_factor_path.write_text(_render_selected_factor_file(source_text, selected_fields, selected_metadata, args.dedup_key), encoding="utf-8")
        selected_meta_path.write_text(json.dumps({"promoted_key": args.dedup_key, "factor_file": str(selected_factor_path), "selected_fields": selected_fields, "factors": selected_metadata}, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "status": "ok",
        "dry_run": args.dry_run,
        "input_factor_count": len(rows_by_field),
        "candidate_count": len(candidates),
        "selected_count_before_group_cap": len(selected_before_group_cap),
        "selected_count": len(selected),
        "max_per_hf_factor": max_per_hf_factor,
        "hf_factor_group_count_before_cap": len(group_sizes),
        "dropped_by_group_cap_count": len(dropped_by_group_cap),
        "dedup_key": args.dedup_key,
        "thresholds_file": str(Path(args.thresholds).resolve()),
        "selection_tier": args.tier,
        "thresholds": threshold_cfg,
        "factor_file": str(selected_factor_path),
        "metadata_file": str(selected_meta_path),
        "selected": selected,
        "dropped_by_group_cap": dropped_by_group_cap[:100],
        "top_rejected": sorted([item for item in candidates if not item["selected"]], key=lambda item: item["score"], reverse=True)[:20],
    }
    if not args.dry_run:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "dry_run", "input_factor_count", "selected_count_before_group_cap", "hf_factor_group_count_before_cap", "max_per_hf_factor", "dropped_by_group_cap_count", "selected_count", "dedup_key", "factor_file", "metadata_file")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
