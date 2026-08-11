#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.factor.core.normalization import normalize_paper_hf_factors  # noqa: E402
from src.factor.proxy.proxy_mapping import attach_paper_factor_proxy_analysis  # noqa: E402


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _publish_reports(report_paths: list[Path], public_reports_dir: Path) -> None:
    public_reports_dir.mkdir(parents=True, exist_ok=True)
    for path in report_paths:
        if path.exists():
            shutil.copy2(path, public_reports_dir / path.name)


def _paper_factors_for_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_paper_hf_factors(row.get("paper_hf_factors") or [])


FAMILY_DATA_ZH = {
    "adverse_selection": "需要主动买卖方向、参与者类别、VPIN/PIN 输入或信息交易标签；当前只能用报价变化乘以成交量做弱代理。",
    "arrival_intensity": "需要事件时间订单/成交明细、精确时间戳和事件标签；普通快照无法还原点过程。",
    "amm_pool_state": "需要 AMM 储备量、swap 事件、池子流动性和链上时间序列。",
    "benchmark_or_residual": "需要同步指数、ETF basket 或市场组合收益；若要残差，还需要滚动回归状态。",
    "benchmark_return_series": "需要 WTI/Brent/指数/ETF/目标资产等外部价格序列，并与本地 tick 对齐。",
    "cross_asset_liquidity": "需要跨品种同步盘口、成交和流动性特征，单一合约本地字段不够。",
    "derivative_funding_state": "需要资金费率、永续合约溢价、持仓量和交易所衍生品状态。",
    "limit_order_lifetime": "需要逐笔委托 ID、下单/撤单时间、订单生命周期；L2 快照只能近似深度变化。",
    "liquidity_tail_risk": "需要极端流动性事件标签、压力市场上下文或跨市场风险变量；本地波动率只能弱代理。",
    "network_contagion": "需要资产网络、相关/持仓/供应链关系和跨资产传播特征。",
    "systematic_flow": "需要市场范围或截面同步的订单流/成交流，用于提取共同流成分。",
    "text_event_signal": "需要公告、新闻、财报、日历、基本面或文本情绪数据。",
}


def _field_set_from_result(path: Path) -> set[str]:
    payload = _load_json(path)
    return {
        str(row.get("factor_field"))
        for row in payload.get("rows", [])
        if isinstance(row, dict) and row.get("factor_field")
    }


def _data_need_zh(canonical: list[str], unresolved: list[str]) -> str:
    needs = [FAMILY_DATA_ZH[name] for name in canonical if name in FAMILY_DATA_ZH]
    if needs:
        return "；".join(dict.fromkeys(needs))
    if unresolved:
        return "需要人工判断这些未归类变量是否可映射到已有 family，或是否需要新增外部数据：" + "；".join(unresolved[:8])
    return "当前数据需求未细化；优先检查 proxy_status_reason 和 ideal_input_fields。"


def _render_policy_markdown(policy: dict[str, Any], health: dict[str, Any]) -> str:
    counts = policy.get("counts", {}) if isinstance(policy.get("counts"), dict) else {}
    proxy = health.get("proxy", {}) if isinstance(health.get("proxy"), dict) else {}
    backtest = health.get("backtest", {}) if isinstance(health.get("backtest"), dict) else {}
    return "\n".join(
        [
            "# Article Pool and Automation Policy",
            "",
            "## 稳定文章池定义",
            "",
            str(policy.get("definition_zh") or ""),
            "",
            "## 保留规则",
            "",
            *[f"- {item}" for item in policy.get("keep_rules", [])],
            "",
            "## 人工审核边界",
            "",
            str(policy.get("manual_review_boundary_zh") or ""),
            "",
            "## 当前计数",
            "",
            f"- 稳定文章池: {counts.get('article_pool_count')}",
            f"- LLM pending: {counts.get('analysis_pending_llm_count')}",
            f"- 明确公式 HF: {proxy.get('formula_ready_hf')}",
            f"- 明确公式代理覆盖: {proxy.get('proxy_covered_formula_ready_hf')} / {proxy.get('formula_ready_hf')}",
            f"- 当前 proxy 缺口: {proxy.get('proxy_gap_count')}",
            f"- 当前 small missing: {backtest.get('small_missing_fields')}",
            "",
        ]
    )


def _article_pool_policy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    v6_count = sum(1 for row in rows if "schema-v6" in str(row.get("analysis_agent", "")))
    v2_count = sum(1 for row in rows if str(row.get("analysis_version", "")) == "v2")
    pending_count = sum(1 for row in rows if bool(row.get("analysis_pending_llm")))
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "article_pool_path": "data/analysis_archive.jsonl",
        "definition_zh": "稳定文章池 = 所有 arXiv 来源且已通过 LLM 解析的文章。目前通过 gpt-4o schema-v6 管道进行增量更新。",
        "keep_rules": [
            "优先处理 arXiv 来源的文章。",
            "跳过 URL 包含 non-arXiv 且 analysis_pending_llm 被标记为 False 的条目。",
        ],
        "manual_review_boundary_zh": "proxy registry 不自动写入；自动程序只生成候选、审核台和报告，最终 registry 合并仍由人工审核 JSON 触发。",
        "counts": {
            "article_pool_count": len(rows),
            "analysis_pending_llm_count": pending_count,
        },
    }


def _llm_pending_queue(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pending: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    for row in rows:
        if not bool(row.get("analysis_pending_llm")):
            continue
        reason = str(row.get("analysis_error") or "pending_llm")[:300]
        reason_counts[reason] += 1
        pending.append(
            {
                "title": row.get("title", ""),
                "url": row.get("url", ""),
                "source_id": row.get("source_id", ""),
                "publish_time": row.get("publish_time", ""),
                "analysis_agent": row.get("analysis_agent", ""),
                "analysis_error": reason,
                "recommendation_score": row.get("recommendation_score", 0),
            }
        )
    pending.sort(key=lambda item: (str(item.get("publish_time") or ""), str(item.get("title") or "")), reverse=True)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pending_count": len(pending),
        "reason_counts": dict(reason_counts.most_common()),
        "items": pending[:300],
    }


def _proxy_coverage_gaps(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    specs = [item for item in manifest.get("specs", []) if isinstance(item, dict)]
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
    gaps: list[dict[str, Any]] = []
    total_formula_ready = 0
    covered_formula_ready = 0
    for row in rows:
        factors = attach_paper_factor_proxy_analysis(_paper_factors_for_row(row))
        row_key = str(row.get("url") or row.get("title") or "")
        for idx, factor in enumerate(factors):
            if not isinstance(factor, dict):
                continue
            plan = factor.get("paper_hf_formula_plan") if isinstance(factor.get("paper_hf_formula_plan"), dict) else {}
            formula = str(plan.get("custom_formula") or "").strip()
            key = (row_key, str(idx))
            if not formula or any(marker in formula.lower() for marker in ("待 llm", "unknown", "todo", "n/a")):
                continue
            total_formula_ready += 1
            if key in covered_keys:
                covered_formula_ready += 1
                continue
            mappings = [item for item in factor.get("proxy_mappings", []) if isinstance(item, dict)]
            unresolved = [str(item) for item in factor.get("unresolved_proxy_variables", []) if str(item)]
            strengths = sorted({str(item.get("proxy_strength") or "") for item in mappings if item.get("proxy_strength")})
            canonical = sorted({str(item.get("canonical_variable") or "") for item in mappings if item.get("canonical_variable")})
            if not mappings and unresolved:
                reason = "缺少 registry 别名或变量族映射"
                action = "人工审核 unresolved 变量，决定 add_alias / new_family / future_pipeline / unsupported"
            elif any(strength in {"future_pipeline", "unsupported"} for strength in strengths):
                reason = "机制依赖当前没有的数据源或不应代理的变量"
                action = "保留人工审核，必要时规划外部数据管线"
            elif any(strength == "weak_proxy" for strength in strengths):
                reason = "只有弱代理，默认不展开 full variants"
                action = "人工确认是否接受弱代理或仅作为展示"
            else:
                reason = "已映射但生成器没有可用模板"
                action = "补充 generate_paper_hf_factor_tests.py 的模板规则"
            gaps.append(
                {
                    "title": row.get("title", ""),
                    "url": row.get("url", ""),
                    "paper_hf_factor_index": idx,
                    "factor_name": factor.get("name", ""),
                    "mechanism_formula": formula,
                    "ideal_input_fields": factor.get("ideal_input_fields", []),
                    "canonical_variables": canonical,
                    "proxy_strengths": strengths,
                    "unresolved_proxy_variables": unresolved,
                    "proxy_status": factor.get("proxy_status", ""),
                    "proxy_status_reason": factor.get("proxy_status_reason", ""),
                    "gap_reason_zh": reason,
                    "recommended_action_zh": action,
                    "required_data_zh": _data_need_zh(canonical, unresolved),
                    "manual_review_required": True,
                }
            )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "formula_ready_paper_hf_factors": total_formula_ready,
        "proxy_covered_formula_ready_factors": covered_formula_ready,
        "gap_count": len(gaps),
        "manual_review_boundary_zh": "本报告只解释缺口；不会自动修改 proxy registry。",
        "items": gaps,
    }


def _slurm_jobs() -> list[dict[str, str]]:
    try:
        proc = subprocess.run(
            ["squeue", "-h", "-u", "gaozh", "-o", "%i|%T|%j|%M|%R"],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except Exception:
        return []
    jobs: list[dict[str, str]] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 4)
        if len(parts) != 5:
            continue
        job_id, state, name, elapsed, reason = parts
        if "paper_hf" not in name and "llm" not in name and "proxy" not in name:
            continue
        jobs.append({"job_id": job_id, "state": state, "name": name, "elapsed": elapsed, "reason": reason})
    return jobs


def _pipeline_health(summary: dict[str, Any], pending: dict[str, Any], gaps: dict[str, Any], slurm_jobs: list[dict[str, str]], paths: dict[str, Path]) -> dict[str, Any]:
    state = _load_json(paths["delta_state"])
    stop_exists = paths["llm_stop"].exists()
    log_exists = paths["llm_log"].exists()
    manifest = _load_json(paths["manifest"])
    specs = [item for item in manifest.get("specs", []) if isinstance(item, dict) and item.get("field")]
    fields = {str(item.get("field")) for item in specs}
    small_fields = _field_set_from_result(paths["small_result"])
    medium_fields = _field_set_from_result(paths["medium_result"])
    large_fields = _field_set_from_result(paths["large_result"])
    status = "ok"
    warnings: list[str] = []
    if stop_exists:
        status = "warning"
        warnings.append("LLM scheduler stop file exists; remove it before starting a new automatic run.")
    if int(pending.get("pending_count") or 0) > 0:
        warnings.append("LLM pending queue is non-empty; hourly job will continue retrying within configured limits.")
    if int(gaps.get("gap_count") or 0) > 0:
        warnings.append("Proxy coverage gaps require manual review or new data/templates.")
    formula_ready_hf = summary.get("formula_ready_paper_hf_factors", gaps.get("formula_ready_paper_hf_factors"))
    proxy_covered_formula_ready_hf = summary.get(
        "formula_ready_paper_hf_factors_generated",
        gaps.get("proxy_covered_formula_ready_factors"),
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "warnings": warnings,
        "llm_scheduler": {
            "stop_file_exists": stop_exists,
            "log_exists": log_exists,
            "log_path": str(paths["llm_log"]),
        },
        "article_pool": {
            "count": summary.get("article_pool_count"),
            "pending_llm_count": pending.get("pending_count"),
        },
        "proxy": {
            "manifest_fields": len(fields),
            "formula_ready_hf": formula_ready_hf,
            "proxy_covered_formula_ready_hf": proxy_covered_formula_ready_hf,
            "proxy_gap_count": gaps.get("gap_count"),
            "manual_review_required": True,
        },
        "backtest": {
            "small_current_fields": len(fields & small_fields),
            "small_missing_fields": len(fields - small_fields),
            "medium_current_fields": len(fields & medium_fields),
            "medium_missing_fields": len(fields - medium_fields),
            "large_current_fields": len(fields & large_fields),
            "large_missing_fields": len(fields - large_fields),
            "last_delta_state": state,
            "active_slurm_jobs": slurm_jobs,
        },
    }


def build_reports(args: argparse.Namespace) -> dict[str, Any]:
    rows = _iter_jsonl(args.article_pool)
    manifest = _load_json(args.manifest)
    summary = _load_json(args.summary)
    policy = _article_pool_policy(rows)
    pending = _llm_pending_queue(rows)
    gaps = _proxy_coverage_gaps(rows, manifest)
    slurm_jobs = _slurm_jobs()
    paths = {
        "delta_state": args.delta_state,
        "llm_stop": args.llm_stop,
        "llm_log": args.llm_log,
        "manifest": args.manifest,
        "small_result": args.small_result,
        "medium_result": args.medium_result,
        "large_result": args.large_result,
    }
    health = _pipeline_health(summary, pending, gaps, slurm_jobs, paths)
    _write_json(args.article_pool_policy_out, policy)
    _write_json(args.llm_pending_out, pending)
    _write_json(args.proxy_gaps_out, gaps)
    _write_json(args.health_out, health)
    _write_text(args.article_pool_policy_md_out, _render_policy_markdown(policy, health))
    if args.publish_public_reports:
        _publish_reports(
            [
                args.health_out,
                args.llm_pending_out,
                args.proxy_gaps_out,
                args.article_pool_policy_out,
                args.article_pool_policy_md_out,
                args.hf_proxy_summary_json,
                args.hf_proxy_summary_html,
            ],
            args.public_reports_dir,
        )
    return health


def main() -> int:
    parser = argparse.ArgumentParser(description="Update operational reports for the paper LLM/proxy/backtest pipeline.")
    parser.add_argument("--article-pool", type=Path, default=ROOT / "data/analysis_archive.jsonl")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/paper_hf_factor_tests_v2/manifest.json")
    parser.add_argument("--summary", type=Path, default=ROOT / "reports/hf_proxy_diversity_summary.json")
    parser.add_argument("--small-result", type=Path, default=ROOT / "data/paper_hf_factor_results_v2/paper_hf_direct_proxy_tests_v2.json")
    parser.add_argument("--medium-result", type=Path, default=ROOT / "data/paper_hf_factor_results_medium1/paper_hf_direct_proxy_tests_v2.json")
    parser.add_argument("--large-result", type=Path, default=ROOT / "data/factor_results_large1_selected_final/paper_hf_relaxed_medium_candidates.json")
    parser.add_argument("--delta-state", type=Path, default=ROOT / "data/runtime/paper_hf_delta_backtest_state.json")
    parser.add_argument("--llm-stop", type=Path, default=ROOT / "logs/llm_v6_key1_hourly_hf_update.stop")
    parser.add_argument("--llm-log", type=Path, default=ROOT / "logs/llm_v6_key1_hourly_hf_update.log")
    parser.add_argument("--health-out", type=Path, default=ROOT / "reports/pipeline_health.json")
    parser.add_argument("--llm-pending-out", type=Path, default=ROOT / "reports/llm_pending_queue.json")
    parser.add_argument("--proxy-gaps-out", type=Path, default=ROOT / "reports/proxy_coverage_gaps.json")
    parser.add_argument("--article-pool-policy-out", type=Path, default=ROOT / "reports/article_pool_policy.json")
    parser.add_argument("--article-pool-policy-md-out", type=Path, default=ROOT / "reports/article_pool_policy.md")
    parser.add_argument("--hf-proxy-summary-json", type=Path, default=ROOT / "reports/hf_proxy_diversity_summary.json")
    parser.add_argument("--hf-proxy-summary-html", type=Path, default=ROOT / "reports/hf_proxy_diversity_summary.html")
    parser.add_argument("--public-reports-dir", type=Path, default=ROOT / "public/reports")
    parser.add_argument("--no-publish-public-reports", dest="publish_public_reports", action="store_false")
    parser.set_defaults(publish_public_reports=True)
    args = parser.parse_args()
    health = build_reports(args)
    print(json.dumps({"status": health.get("status"), "warnings": health.get("warnings", []), "health_out": str(args.health_out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
