#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[2]
DAY = datetime.now(timezone.utc).strftime("%Y%m%d")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _archive_evidence_by_title() -> Dict[str, Dict[str, object]]:
    out: Dict[str, Dict[str, object]] = {}
    for row in _read_jsonl(ROOT / "data" / "arxiv_evidence_archive.jsonl"):
        pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
        if pack.get("status") == "ok" and (pack.get("quality_checks") or {}).get("is_trusted"):
            out[str(row.get("title") or "")] = pack
    return out


def _score_dimensions(relevance: int, mechanism: int, statistical: int, implementation: int, cost: int, generality: int, evidence: str, critique: str) -> Dict[str, Dict[str, object]]:
    return {
        "relevance": {"label": "相关性", "score": relevance, "comment": "基于原文机制与本地高频研究目标的相关性评分。", "evidence": evidence, "critique": critique},
        "mechanism": {"label": "机制可信度", "score": mechanism, "comment": "是否有清楚的原文公式、变量或机制链条。", "evidence": evidence, "critique": critique},
        "statistical": {"label": "统计可信度", "score": statistical, "comment": "当前 evidence 是否披露样本、检验或稳健性。", "evidence": evidence, "critique": critique},
        "implementation": {"label": "可实现性", "score": implementation, "comment": "本地字段能否直接或近似支持。", "evidence": evidence, "critique": critique},
        "cost_sensitivity": {"label": "成本敏感性", "score": cost, "comment": "是否显式考虑交易成本、流动性、延迟或容量。", "evidence": evidence, "critique": critique},
        "generality": {"label": "普适性", "score": generality, "comment": "跨市场、跨样本或跨机制迁移的可能性。", "evidence": evidence, "critique": critique},
    }


def _base_row(title: str, url: str, summary: str, tags: List[str], evidence: Dict[str, object], core_idea: str, structured_summary: Dict[str, str], factors: List[Dict[str, object]], scores: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    return {
        "publish_time": "2026-07-13T00:00:00Z",
        "source_type": "paper",
        "source_name": "arXiv q-fin",
        "source_id": "arxiv_qf",
        "title": title,
        "summary": summary,
        "url": url,
        "tags": tags,
        "fetched_at": NOW,
        "dedup_key": "no_key_" + url.rsplit("/", 1)[-1].replace(".", "_"),
        "llm_input_evidence_pack": evidence,
        "analysis_agent": "no-key-evidence-parser:selected-v1",
        "analysis_pending_llm": False,
        "core_idea": core_idea,
        "structured_summary": structured_summary,
        "hf_factor_points": [str(f.get("meaning") or f.get("paper_mechanism") or "")[:220] for f in factors[:3]],
        "paper_hf_factors": factors,
        "factor_candidates": [],
        "score_dimensions": scores,
        "recommendation_score": round(sum(float(v.get("score", 0)) for v in scores.values()) / max(1, len(scores)), 1),
    }


def what_useful_alphas(evidence: Dict[str, object]) -> Dict[str, object]:
    factors = [
        {
            "name": "Post-2005 anomaly shrinkage residual score",
            "frequency": "monthly evidence; high-frequency use only as a gating/diagnostic score",
            "mechanism_category": "prediction_residual",
            "mechanism_type": "spread_adjusted_residual",
            "mechanism_formula": "r_adj = (1 - 1 / Var(t_cross_section)) * r_anomaly; signal = zscore(r_adj - estimated_cost)",
            "paper_hf_formula_plan": {"template_id": "paper_hf_local_residual_return", "operator_family": "residual_shrinkage", "inputs": ["anomaly_return", "t_statistic", "transaction_cost_estimate"], "windows": ["post_2005", "rolling_cross_section"], "normalization": "cross_sectional_zscore_after_shrinkage", "direction": "positive", "custom_formula": "zscore(anomaly_return * (1 - 1 / (1 + t_statistic * t_statistic)) - transaction_cost_estimate)", "rationale": "原文公式给出 r_adj=(1-1/Var(t))r，用于处理多 predictor 幸运表现。", "fallback_template": "paper_hf_abstract_rl_forecast_residual_shadow"},
            "meaning": "保留论文中对 published anomaly return 做噪声 shrinkage 的机制，而不是直接相信原始 anomaly 收益。",
            "ideal_input_fields": ["published_anomaly_return", "cross_sectional_t_statistic", "transaction_cost_estimate", "investable_universe_flag"],
            "variable_roles": [{"variable": "r", "role": "anomaly mean return"}, {"variable": "t", "role": "return divided by standard error"}, {"variable": "Var(t)", "role": "cross-sectional t-statistic variance"}],
            "paper_mechanism": "公式 evidence 给出 r_adj=(1-1/Var(t))r，并解释它用于 account for lucky performance among many predictors。",
            "source_evidence": "formula_contexts: r_adj=[1-1/Var(t)]r; intro_context: minimal transaction costs would have eliminated even this.",
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
            "paper_hf_formula_plan": {"template_id": "paper_hf_cost_adjusted_score", "operator_family": "cost_adjusted_filter", "inputs": ["all_stock_anomaly_return", "non_micro_post_2005_return", "spread_or_cost_proxy"], "windows": ["post_2005", "rolling_monthly"], "normalization": "zscore(decay_score)", "direction": "negative", "custom_formula": "zscore(all_stock_anomaly_return - non_micro_post_2005_return - spread_or_cost_proxy)", "rationale": "原文主要机制是 alpha 在可投资股票和后 2005 样本中衰减。", "fallback_template": "paper_hf_spread_adjusted_return"},
            "meaning": "若一个公开 anomaly 的收益主要来自微盘或发表前样本，应降低或反向其本地高频使用优先级。",
            "ideal_input_fields": ["anomaly_return_all_stocks", "anomaly_return_non_micro", "post_2005_flag", "market_cap_rank", "cost_proxy"],
            "variable_roles": [{"variable": "non_micro_post_2005_return", "role": "investable modern-sample return"}, {"variable": "cost_proxy", "role": "transaction cost penalty"}],
            "paper_mechanism": "method_blocks 披露 top 3000 与 top 90% market cap 过滤；intro_context 披露 post-2005 non-micro returns fall to around 7 bps/month。",
            "source_evidence": "intro_context: top 90% market capitalization; post-2005; 7 bps per month; minimal transaction costs would erase.",
            "novelty_reason": "不是寻找新的高频 alpha，而是为已有 anomaly 加入可投资性和发表后衰减门控。",
            "classic_baseline": "unfiltered anomaly long-short portfolio",
            "unobservable_variables": ["full anomaly membership", "monthly anomaly portfolio returns"],
            "minimum_data_needed": ["market cap ranks", "post-2005 monthly anomaly returns", "transaction cost proxy"],
        },
    ]
    return _base_row(
        "What Useful Alphas?",
        "https://arxiv.org/abs/2607.06502",
        "Re-examines published anomaly portfolios and argues that post-2005 non-microcap investable returns are close to zero after noise and cost adjustments.",
        ["arxiv", "anomaly", "transaction cost", "portfolio", "post-2005"],
        evidence,
        "公开 anomaly alpha 在后 2005、非微盘和交易成本/噪声调整后大幅衰减；最大风险是论文使用月频组合证据，不能直接推出可交易高频 alpha。",
        {"problem": "已发表 anomaly 在真实可投资股票和现代样本中是否仍有用。", "method": "使用 Chen-Zimmermann anomaly 组合，按 post-2005 与 non-microcap universe 过滤，并用 shrinkage 调整幸运表现。", "data": "openassetpricing anomaly 月频 long-short returns；top 3000 / top 90% market cap 过滤。", "author_claim": "post-2005 non-micro median return 约 7 bps/month，轻微交易成本即可消除。", "limitations": "不是高频微观结构论文，不能直接推出 tick alpha。", "critical_assessment": "适合作为 anomaly 风险过滤器，不适合作为独立高频 alpha。", "missing_tests": "需要成本后、容量、滚动样本外和本地 universe 复现。", "key_results": "r_adj=(1-1/Var(t))r；median CAPM alpha 约 9 bps/month，median t-stat 约 0.64。"},
        factors,
        _score_dimensions(6, 7, 6, 4, 8, 5, "r_adj=(1-1/Var(t))r; 7 bps/month; minimal costs erase", "月频组合证据，非直接高频 alpha。"),
    )


def financial_epiplexity(evidence: Dict[str, object]) -> Dict[str, object]:
    factors = [
        {
            "name": "Bounded-compute structure gain",
            "frequency": "rolling window; horizon/task dependent",
            "mechanism_category": "prediction_residual",
            "mechanism_type": "model_description_gain",
            "mechanism_formula": "gain_t = code_length(baseline_model, W_t) - code_length(best_budgeted_model, W_t) - description_penalty",
            "paper_hf_formula_plan": {"template_id": "paper_hf_price_forecast_score_proxy", "operator_family": "conditional_expectation", "inputs": ["return", "realized_volatility", "volume", "order_book_features"], "windows": ["rolling_task_window"], "normalization": "zscore(gain_t)", "direction": "positive", "custom_formula": "zscore(return - rolling_mean(return) + realized_volatility + volume)", "rationale": "原文定义 bounded-compute learnable market structure 和 rolling gain；本地只能用预测残差/稳定性作弱代理。", "fallback_template": "paper_hf_abstract_prediction_market_shadow"},
            "meaning": "度量有限模型在给定预算、表征和目标下相对基线能学到多少可复用市场结构。",
            "ideal_input_fields": ["feature_representation", "target_return_or_drawdown", "baseline_code_length", "budgeted_model_code_length", "model_description_length"],
            "variable_roles": [{"variable": "D_T,h^R", "role": "represented dataset for task/horizon"}, {"variable": "B", "role": "compute/memory/latency/cost budget"}, {"variable": "L_R(M)", "role": "model and representation description length"}],
            "paper_mechanism": "原文称 financial epiplexity is bounded-compute learnable market structure，并给出 time-bounded financial MDL 与 rolling gain 定义。",
            "source_evidence": "method_blocks: B=(B_train,B_eval,B_mem,B_search,B_lat,B_cost); empirical: rolling gain on D_{t-w+1:t,h}^R.",
            "novelty_reason": "相对普通预测准确率，惩罚模型描述长度、计算预算和可迁移结构。",
            "classic_baseline": "raw predictive accuracy or entropy",
            "unobservable_variables": ["true code length", "full model class search", "private representation map"],
            "minimum_data_needed": ["features", "target", "baseline model", "budgeted model", "rolling validation loss"],
        }
    ]
    return _base_row(
        "Financial Epiplexity: A Theory of Learnable Market Structure under Bounded Computation",
        "https://arxiv.org/abs/2607.02695",
        "Defines financial epiplexity as bounded-compute learnable market structure relative to representation, budget, target and horizon.",
        ["arxiv", "learnability", "MDL", "bounded computation", "market structure"],
        evidence,
        "论文的高频启发不是直接订单簿公式，而是要求任何可交易信号必须在有限样本、有限计算、有限延迟和成本约束下显示可复用结构。",
        {"problem": "传统 entropy/MI/accuracy 没有回答有限模型能从金融数据中学到多少有用结构。", "method": "用 time-bounded financial MDL、表征映射和预算约束定义 epiplexity。", "data": "理论框架，示例包含 returns、realized volatility、volume、sector factors、macro/news/option skew 等表征。", "author_claim": "financial epiplexity 是 bounded-compute learnable market structure。", "limitations": "当前 evidence 未披露实证回测；很多量需要外部模型训练估计。", "critical_assessment": "适合作为信号筛选准则，不能单独生成无需训练的本地因子。", "missing_tests": "需要滚动窗口 out-of-sample、成本后收益、延迟约束和表征挖掘惩罚。", "key_results": "time-bounded MDL、rolling epiplexity/gain、预算向量 B。"},
        factors,
        _score_dimensions(7, 7, 4, 3, 6, 6, "bounded-compute learnable market structure; B=(train,eval,mem,search,lat,cost)", "理论强、直接本地可算性弱。"),
    )


def cap_axis(evidence: Dict[str, object]) -> Dict[str, object]:
    factors = [
        {
            "name": "Cap-axis bridge alpha curve",
            "frequency": "daily/monthly depending on factor model estimation",
            "mechanism_category": "continuous_functional",
            "mechanism_type": "cap_rank_pricing_error",
            "mechanism_formula": "D_t(p)=C_t(p)-pR_t^M; D_t(p)=alpha_m(p)+beta_m(p)'f_{m,t}+epsilon_{m,t}(p)",
            "paper_hf_formula_plan": {"template_id": "paper_hf_local_residual_return", "operator_family": "rolling_integral", "inputs": ["cap_ranked_returns", "market_return", "factor_returns"], "windows": ["formation_window", "HAC_window"], "normalization": "curve_functionals", "direction": "signed", "custom_formula": "zscore(cap_ranked_returns - market_return - factor_returns)", "rationale": "原文沿市值轴构造 prefix bridge 并估计 bridge-alpha curve；本地高频只能作为横截面残差诊断。", "fallback_template": "paper_hf_local_common_flow_pressure"},
            "meaning": "检测因子模型在市值排名轴上哪里留下定价误差。",
            "ideal_input_fields": ["market_cap_rank", "asset_return", "market_return", "factor_return_vector"],
            "variable_roles": [{"variable": "p", "role": "cumulative market-value cutoff"}, {"variable": "D_t(p)", "role": "prefix bridge zero-investment return"}, {"variable": "alpha_m(p)", "role": "cap-axis pricing error curve"}],
            "paper_mechanism": "原文定义 C_t(p)=int_0^p r_t(u)du，D_t(p)=C_t(p)-pR^M_t，并回归出 alpha_m(p)。",
            "source_evidence": "formula_contexts: R^M_t=∫r_t(u)du; C_t(p)=∫_0^p r_t(u)du; D_t(p)=C_t(p)-pR^M_t; alpha_m(p)=0 null.",
            "novelty_reason": "不是普通 size factor，而是沿连续市值轴扫描模型定价误差位置、方向和面积。",
            "classic_baseline": "single size factor loading or aggregate alpha test",
            "unobservable_variables": ["full CRSP-like investable universe", "market-cap sorted infinitesimal portfolio"],
            "minimum_data_needed": ["market cap", "returns", "market return", "factor returns", "formation dates"],
        }
    ]
    return _base_row(
        "A Cap-Axis Integral Diagnostic of Factor Models",
        "https://arxiv.org/abs/2607.01765",
        "Builds a cap-axis bridge-alpha curve to diagnose where factor models leave pricing errors along the capitalization-rank axis.",
        ["arxiv", "factor model", "cap axis", "pricing error", "integral"],
        evidence,
        "论文提供的是沿市值排名轴的因子模型诊断：桥接组合的 alpha 曲线指出定价误差集中在大盘、中段还是尾部。",
        {"problem": "传统 joint alpha 或 Sharpe 比较不能定位因子模型在市值轴上的错误。", "method": "按 market-value rank 构造 prefix contribution、bridge return 和 bridge-alpha curve。", "data": "CRSP investable market，daily value-weighted buy-and-hold aggregate market，Fama-French/q-factor 对照。", "author_claim": "模型可通过 aggregate market gate 但仍在 cap-rank bridge family 留下非零 alpha。", "limitations": "需要完整横截面、市值排序和因子收益；不是单资产 tick 因子。", "critical_assessment": "适合作为模型诊断和横截面风险过滤，不适合直接当盘口 alpha。", "missing_tests": "需要本地市场 cap-rank universe、频率选择、HAC/GP null 和 ordering placebo。", "key_results": "D_t(p)=C_t(p)-pR^M_t，D_t(p)=alpha_m(p)+beta_m(p)'f_t+epsilon_t(p)。"},
        factors,
        _score_dimensions(7, 8, 7, 4, 3, 6, "D_t(p)=C_t(p)-pR^M_t; bridge-alpha curve", "需要完整横截面市值轴，非单票高频可直接计算。"),
    )


def ai_premium(evidence: Dict[str, object]) -> Dict[str, object]:
    factors = [
        {
            "name": "Rolling AI beta exposure",
            "frequency": "weekly in paper; local use as external-factor exposure gate",
            "mechanism_category": "prediction_residual",
            "mechanism_type": "rolling_factor_beta",
            "mechanism_formula": "ret_{i,tau}=alpha_{i,t}+beta_AI_{i,t} AI_tau+beta_rm_{i,t} r_m_tau+epsilon_{i,tau}",
            "paper_hf_formula_plan": {"template_id": "paper_hf_local_residual_return", "operator_family": "conditional_expectation", "inputs": ["stock_return", "AI_factor", "market_return"], "windows": ["13_week_min_9"], "normalization": "zscore(beta_AI)", "direction": "positive", "custom_formula": "zscore(rolling_beta(stock_return - market_return, AI_factor))", "rationale": "原文用滚动周回归估计 AI beta；本地若无 OpenRouter AI factor，只能作为外部因子暴露门控。", "fallback_template": "paper_hf_abstract_prediction_market_shadow"},
            "meaning": "衡量个股价格对实现 AI 消费增长因子的市场隐含暴露。",
            "ideal_input_fields": ["stock_weekly_return", "AI_consumption_factor", "market_return", "formation_week"],
            "variable_roles": [{"variable": "AI_tau", "role": "baseline AI factor from OpenRouter consumption"}, {"variable": "beta_AI", "role": "market-implied AI exposure"}, {"variable": "r_m", "role": "market return control"}],
            "paper_mechanism": "公式 evidence 明确将股票超额收益回归到 AI factor 与 market return，并用 13-week window 每周重估 beta_AI。",
            "source_evidence": "formula_contexts: ret_i_tau = alpha + beta_AI AI_tau + beta_rm r_m_tau + epsilon; 13-week estimation window, minimum 9 weeks.",
            "novelty_reason": "相对普通科技/动量因子，使用实际 AI token consumption 构造外部冲击因子。",
            "classic_baseline": "market beta or technology-sector exposure",
            "unobservable_variables": ["licensed OpenRouter token-consumption panel", "AI_factor components"],
            "minimum_data_needed": ["weekly stock returns", "AI factor", "market return", "rolling regression window"],
        }
    ]
    return _base_row(
        "AI Premium",
        "https://arxiv.org/abs/2606.30583",
        "Constructs an AI consumption factor from OpenRouter token usage and estimates firms' rolling market-implied AI exposure.",
        ["arxiv", "AI", "asset pricing", "rolling beta", "OpenRouter"],
        evidence,
        "论文的核心可转化机制是外部 AI 消费冲击因子与股票收益的滚动 beta 暴露，而不是直接从盘口生成 AI alpha。",
        {"problem": "AI 需求增长如何被股票市场定价。", "method": "用 OpenRouter token consumption 构造 AI factor，并用 13-week rolling regression 估计 firm-level AI beta。", "data": "OpenRouter user-model-day panel，约 380 trillion tokens，CRSP/Compustat 等股票数据。", "author_claim": "高 AI beta 股票有 AI premium，且 exposure 每周重估避免 look-ahead。", "limitations": "OpenRouter 数据不可本地直接观测；当前只能作为外部因子或代理信号。", "critical_assessment": "机制明确但实现依赖专有外部数据；本地 tick 代理不能凭空替代 AI factor。", "missing_tests": "需要样本外、成本后、国际市场和替代 AI proxy 稳健性。", "key_results": "beta_AI 来自 ret 对 AI factor 和 market return 的 13-week rolling regression。"},
        factors,
        _score_dimensions(8, 8, 7, 3, 4, 7, "ret=alpha+beta_AI*AI+beta_rm*r_m+epsilon; 13-week window", "核心 AI factor 依赖外部专有数据，本地不可直接观测。"),
    )


def write_comparison() -> None:
    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    comparison = {
        "article": "What Useful Alphas?",
        "old_version": {
            "agent": "paper-manual-agent:copilot-local-arxiv-batch-05:schema-v6",
            "factor_names": ["alpha_execution_cost_gate", "alpha_flow_confirmation"],
            "issue": "旧版把论文强行转成本地 tick 执行/OBI 因子，使用 order_size、execution_friction、realized_volatility、order_book_imbalance 等变量；这些不是该文原始推导的核心变量。",
        },
        "new_no_key_version": {
            "agent": "no-key-evidence-parser:selected-v1",
            "factor_names": ["Post-2005 anomaly shrinkage residual score", "Investable-universe alpha decay filter"],
            "improvement": "新版只保留原文明确支持的 post-2005、non-micro、transaction cost、Bayes-Stein shrinkage 和 investable-universe 衰减机制。",
        },
        "verdict": "新版更忠实；它承认该文不是直接高频 alpha 论文，而是公开 anomaly 的可投资性/成本/shrinkage 过滤框架。",
    }
    (reports / "what_useful_alphas_factor_diff.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    (reports / "what_useful_alphas_factor_diff.md").write_text(
        "# What Useful Alphas? 因子差异\n\n"
        "旧版因子：`alpha_execution_cost_gate`, `alpha_flow_confirmation`。问题是它们把文章强行转成 tick 执行/OBI 因子，"
        "但原文核心并不是订单簿或成交流。\n\n"
        "新版 no-key 因子：`Post-2005 anomaly shrinkage residual score`, `Investable-universe alpha decay filter`。"
        "它们直接来自原文的 post-2005、non-micro、transaction cost、`r_adj=(1-1/Var(t))r` shrinkage 机制。\n\n"
        "结论：新版更忠实于原文；它把该文视为 anomaly 可投资性/成本/shrinkage 过滤框架，而不是直接高频 alpha。\n",
        encoding="utf-8",
    )


def main() -> int:
    by_title = _archive_evidence_by_title()
    first_evidence = _read_json(ROOT / "reports" / "evidence_probe_first_seed.json")
    rows = [
        what_useful_alphas(first_evidence),
        financial_epiplexity(by_title["Financial Epiplexity: A Theory of Learnable Market Structure under Bounded Computation"]),
        cap_axis(by_title["A Cap-Axis Integral Diagnostic of Factor Models"]),
        ai_premium(by_title["AI Premium"]),
    ]
    _write_jsonl(ROOT / "data" / "latest.jsonl", rows)
    _write_jsonl(ROOT / "data" / "analysis_archive.jsonl", rows)
    _write_jsonl(ROOT / "data" / f"daily_{DAY}.jsonl", rows)
    write_comparison()
    print(json.dumps({"rows": len(rows), "titles": [row["title"] for row in rows], "comparison": "reports/what_useful_alphas_factor_diff.md"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())