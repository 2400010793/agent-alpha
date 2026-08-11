#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_jsonl(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _row_from_what_useful_alphas(evidence: Dict[str, object]) -> Dict[str, object]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    title = "What Useful Alphas?"
    url = str(evidence.get("url") or "https://arxiv.org/abs/2607.06502")
    return {
        "publish_time": "2026-07-08T00:00:00Z",
        "source_type": "paper",
        "source_name": "arXiv q-fin",
        "source_id": "arxiv_qf",
        "title": title,
        "summary": (
            "The paper re-examines roughly 200 published long-short anomaly portfolios and argues that, "
            "after restricting to post-2005 non-microcap stocks and allowing for noise or transaction costs, "
            "the median investable anomaly return is economically close to zero."
        ),
        "url": url,
        "tags": ["arxiv", "anomaly", "transaction cost", "portfolio", "post-2005"],
        "fetched_at": now,
        "dedup_key": "no_key_arxiv_2607_06502",
        "llm_input_evidence_pack": evidence,
        "analysis_agent": "no-key-evidence-parser:v1",
        "analysis_pending_llm": False,
        "core_idea": (
            "公开 anomaly alpha 在后 2005、非微盘和交易成本/噪声调整后大幅衰减；最大风险是论文使用月频组合证据，"
            "不能直接推出可交易的高频 alpha。"
        ),
        "structured_summary": {
            "problem": "论文问的是：已经发表的约 200 个横截面 anomaly，在真实非微盘组合经理可交易的股票和现代市场时期中是否仍有用。",
            "method": "作者使用 Chen-Zimmermann openassetpricing anomaly 组合，按后 2005 和非微盘/大市值可投资股票池过滤，并用简单 Bayes-Stein shrinkage 调整多策略幸运表现。",
            "data": "证据包披露数据来自 openassetpricing.com 的 anomaly 数据集，组合为月频 long-short，样本被切为 2005 年前后，并使用 top 3000 / top 90% 市值等可投资 universe 过滤。",
            "author_claim": "Introduction 中明确称，post-2005 且 non-micro 的 median zero-investment return 约 7 bps/month，median CAPM alpha 约 9 bps/month，median t-statistic 约 0.64，轻微交易成本即可消除。",
            "limitations": "当前 evidence 未提供完整表格数值和所有 anomaly 逐项结果；论文证据是月频组合层面，不能直接等价为 tick/high-frequency 信号。",
            "critical_assessment": "结论对高频因子有负面筛选意义：它支持对历史 anomaly 做 investability、post-publication、cost-adjusted shrinkage，但不支持把单个 anomaly 直接当作高频 alpha。",
            "missing_tests": "需要对本地 tick 数据做滚动样本外、成本后收益、容量、换手和非微盘过滤复现；输入未披露逐项 anomaly 的完整字段定义。",
            "key_results": "核心短证据包括：non-micro post-2005 median return 约 7 bps/month、median CAPM alpha 约 9 bps/month、median t-statistic 约 0.64，以及 shrinkage 公式 r_adj=(1-1/Var(t))r。",
        },
        "hf_factor_points": [
            "用交易成本和可投资 universe 过滤公开 anomaly，避免微盘和发表前样本带来的虚假 alpha。",
            "用横截面 t 统计量方差做 shrinkage，把多重检验中的幸运收益向零或均值收缩。",
        ],
        "paper_hf_factors": [
            {
                "name": "Post-2005 anomaly shrinkage residual score",
                "frequency": "monthly evidence; high-frequency use only as a gating/diagnostic score",
                "mechanism_category": "prediction_residual",
                "mechanism_type": "spread_adjusted_residual",
                "mechanism_formula": "r_adj = (1 - 1 / Var(t_cross_section)) * r_anomaly; signal = zscore(r_adj - estimated_cost)",
                "paper_hf_formula_plan": {
                    "template_id": "paper_hf_local_residual_return",
                    "operator_family": "residual_shrinkage",
                    "inputs": ["anomaly_return", "t_statistic", "transaction_cost_estimate"],
                    "windows": ["post_2005", "rolling_cross_section"],
                    "normalization": "cross_sectional_zscore_after_shrinkage",
                    "direction": "positive",
                    "rationale": "论文公式明确给出 r_adj=(1-1/Var(t))r，用于处理多 predictor 幸运表现；本地若无原始 anomaly 数据，只能降级为 residual-return proxy。",
                    "fallback_template": "paper_hf_abstract_rl_forecast_residual_shadow",
                },
                "meaning": "保留论文中对 published anomaly return 做噪声 shrinkage 的机制，而不是直接相信原始 anomaly 收益。",
                "ideal_input_fields": ["published_anomaly_return", "cross_sectional_t_statistic", "transaction_cost_estimate", "investable_universe_flag"],
                "variable_roles": [
                    {"variable": "r", "role": "论文中的 anomaly mean return"},
                    {"variable": "t", "role": "收益除以标准误后的 t-statistic"},
                    {"variable": "Var(t)", "role": "横截面 t-statistic 方差，用于估计幸运成分"},
                    {"variable": "estimated_cost", "role": "交易成本扣减项，论文称轻微成本会消除剩余收益"},
                ],
                "paper_mechanism": "公式 evidence 给出 r_adj=(1-1/Var(t))r，并解释它用于 account for lucky performance among many predictors。",
                "source_evidence": "formula_contexts: r_adj = [1 - 1/Var(t)] r; intro_context: even minimal transaction costs would have eliminated even this.",
                "novelty_reason": "相对普通 anomaly/momentum，核心是发表后、非微盘、成本和多重检验 shrinkage 后再判断 alpha。",
                "classic_baseline": "raw published long-short anomaly return",
                "unobservable_variables": ["full anomaly panel", "per-anomaly t-statistic", "realized transaction cost"],
                "minimum_data_needed": ["published anomaly monthly returns", "market-cap universe filter", "post-2005 sample split", "transaction cost estimate"],
            },
            {
                "name": "Investable-universe alpha decay filter",
                "frequency": "monthly evidence; high-frequency use only as universe/risk filter",
                "mechanism_category": "prediction_residual",
                "mechanism_type": "portfolio_policy",
                "mechanism_formula": "decay_score = anomaly_return_all_stocks - anomaly_return_non_micro_post_2005 - estimated_cost",
                "paper_hf_formula_plan": {
                    "template_id": "paper_hf_cost_adjusted_score",
                    "operator_family": "cost_adjusted_filter",
                    "inputs": ["all_stock_anomaly_return", "non_micro_post_2005_return", "spread_or_cost_proxy"],
                    "windows": ["post_2005", "rolling_monthly"],
                    "normalization": "zscore(decay_score)",
                    "direction": "negative",
                    "rationale": "论文的主要机制是 alpha 在可投资股票和后 2005 样本中衰减，且交易成本进一步削弱。",
                    "fallback_template": "paper_hf_spread_adjusted_return",
                },
                "meaning": "把论文结论转成过滤器：若一个公开 anomaly 的收益主要来自微盘或发表前样本，应降低或反向其本地高频使用优先级。",
                "ideal_input_fields": ["anomaly_return_all_stocks", "anomaly_return_non_micro", "post_2005_flag", "market_cap_rank", "cost_proxy"],
                "variable_roles": [
                    {"variable": "non_micro_post_2005_return", "role": "可投资现代样本收益"},
                    {"variable": "all_stock_anomaly_return", "role": "原论文/全股票 anomaly 收益上限"},
                    {"variable": "cost_proxy", "role": "交易成本和流动性惩罚"},
                ],
                "paper_mechanism": "method_blocks 披露 top 3000 与 top 90% market cap 过滤；intro_context 披露 post-2005 non-micro returns fall to around 7 bps/month。",
                "source_evidence": "intro_context: top 90% market capitalization; post-2005; 7 bps per month; minimal transaction costs would erase.",
                "novelty_reason": "不是寻找新的高频 alpha，而是为已有 anomaly 加入可投资性和发表后衰减门控。",
                "classic_baseline": "unfiltered anomaly long-short portfolio",
                "unobservable_variables": ["full anomaly membership", "microcap classification for every month", "monthly anomaly portfolio returns"],
                "minimum_data_needed": ["market cap ranks", "post-2005 monthly anomaly returns", "transaction cost proxy", "universe filter"],
            },
        ],
        "factor_candidates": [],
        "score_dimensions": {
            "relevance": {"label": "相关性", "score": 6, "comment": "对因子筛选和公开 anomaly 衰减很相关，但不是直接高频微观结构论文。", "evidence": "post-2005 non-micro returns around 7 bps/month", "critique": "月频组合证据不能直接转成 tick alpha。"},
            "mechanism": {"label": "机制可信度", "score": 7, "comment": "机制清晰：样本选择、微盘剔除、交易成本和 shrinkage。", "evidence": "r_adj=(1-1/Var(t))r", "critique": "本地复现需要完整 anomaly panel。"},
            "statistical": {"label": "统计可信度", "score": 6, "comment": "论文显式处理多 predictor 幸运表现。", "evidence": "median t-statistic 0.64; shrinkage formula", "critique": "当前输入未披露完整表格和稳健性细节。"},
            "implementation": {"label": "可实现性", "score": 4, "comment": "需要外部 anomaly 月频组合和市值过滤，不是本地 tick 字段直接可算。", "evidence": "openassetpricing dataset; top 3000/top 90% filters", "critique": "缺少 anomaly membership 与交易成本明细。"},
            "cost_sensitivity": {"label": "成本敏感性", "score": 8, "comment": "成本是论文核心结论之一。", "evidence": "minimal transaction costs would have eliminated even this", "critique": "未披露可直接用于本地市场的成本模型。"},
            "generality": {"label": "普适性", "score": 5, "comment": "适合作为公开 anomaly 的风险过滤框架。", "evidence": "about 200 anomaly portfolios", "critique": "限于美国股票和公开 anomaly 数据集。"},
        },
        "recommendation_score": 6.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a no-key parsed article row from an arXiv evidence JSON.")
    parser.add_argument("--evidence", type=Path, default=ROOT / "reports" / "evidence_probe_first_seed.json")
    parser.add_argument("--day", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    args = parser.parse_args()
    evidence = _read_json(args.evidence)
    row = _row_from_what_useful_alphas(evidence)
    _write_jsonl(ROOT / "data" / "latest.jsonl", [row])
    _write_jsonl(ROOT / "data" / "analysis_archive.jsonl", [row])
    _write_jsonl(ROOT / "data" / f"daily_{args.day}.jsonl", [row])
    print(json.dumps({"wrote": ["data/latest.jsonl", "data/analysis_archive.jsonl", f"data/daily_{args.day}.jsonl"], "title": row["title"], "factor_count": len(row["paper_hf_factors"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())