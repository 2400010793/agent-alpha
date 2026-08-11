#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data" / "arxiv_seed_articles_from_new_daily_all_resolved_unique.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "arxiv_stage1_registry_gate.jsonl"
DEFAULT_REPORT = ROOT / "reports" / "arxiv_stage1_registry_gate_summary.json"
DEFAULT_LLM_INPUT = ROOT / "data" / "arxiv_stage1_llm_screening_input.jsonl"
DEFAULT_LLM_PROMPT = ROOT / "reports" / "arxiv_stage1_llm_screening_prompt.md"


STAGE1_LLM_PROMPT = """你是量化研究论文第一阶段筛选器。目标不是生成新因子，也不是判断是否一定能改进 registry；目标是只筛出属于 4、5、11 三类研究方向的论文。

只允许保留这些论文：
4_time_series_volatility_risk: 时间序列预测、波动率、尾部风险、跳跃、相关性、风险状态、regime 或 drift 监控。
5_order_book_order_flow_microstructure: 订单簿、订单流、流动性、价差、深度、冲击、做市、知情交易、跨资产订单流或执行摩擦。
11_nonstationarity_drift_regime_control: 非平稳性、概念漂移、在线自适应、regime-invariant、walk-forward 稳健性、鲁棒归一化。

必须拒绝：
- 不属于 4、5、11 的论文，即使可能有金融背景也拒绝。
- 只讨论 Agent/LLM 框架、benchmark、能力评估、投资流程，但不涉及 4/5/11。
- 只讨论组合优化、资产配置、Black-Litterman、宏观、资产定价解释、因子模型评价，但不涉及 4/5/11。
- 只讨论 crypto/Polymarket/稳定币基本面，除非明确涉及订单流、流动性、波动率、市场冲击或微观结构。
- 只讨论另类数据、GNN、多模态、量子、优化加速、通用统计方法，除非明确属于 4/5/11。
- 包含证券、银行、存款、贷款、信用风险、债券等硬剔除主题的论文已经在 LLM 前被移除，不应进入此筛选。

请只输出严格 JSON：
{
    "stage1_decision": "eligible" | "reject",
    "primary_category": "4_time_series_volatility_risk" | "5_order_book_order_flow_microstructure" | "11_nonstationarity_drift_regime_control" | "reject_not_4_5_11" | "reject_hard_exclusion_theme" | "reject_too_generic_or_indirect",
    "confidence": 0.0,
    "category_evidence": "一句中文说明：为什么它属于或不属于 4/5/11",
    "evidence_phrases": ["从标题或摘要摘出的短证据"]
}
"""


HARD_EXCLUSION_RULES: dict[str, list[str]] = {
        "reject_security_or_bank_topic": [
                "securities", "security lending", "security market", "security markets", "securities market",
                "bank", "banks", "banking", "depositor", "depositors", "deposit", "deposits",
                "loan", "loans", "lending", "borrower", "mortgage", "mortgages",
                "credit risk", "credit default", "default risk", "bond", "bonds", "treasury", "treasuries",
                "cryptocurrency", "crypto", "stablecoin", "bitcoin", "defi", "blockchain",
                "polymarket", "polymarkets", "polymarket.com", "nba",
                "证券", "银行", "存款", "贷款", "借贷", "信贷", "信用风险", "债券", "国债","保险","加密","体育","博彩"
        ],
}


ELIGIBLE_CATEGORIES: dict[str, dict[str, Any]] = {
    "time_series_volatility_risk": {
        "label": "4_time_series_volatility_risk",
        "strong_keywords": [
            "realized volatility", "rough volatility", "stochastic volatility", "volatility forecasting",
            "volatility forecast", "garch", "hawkes", "jump risk", "tail risk", "heavy-tailed",
            "expected shortfall", "dynamic correlation", "time series forecasting", "risk forecast",
            "volatility surface", "covariance forecasting",
        ],
        "weak_keywords": [
            "volatility", "variance", "realized", "jump", "tail", "forecasting", "time series", "temporal",
            "regime", "drawdown", "var", "covariance", "correlation", "dependence", "intensity",
            "duration", "survival", "hazard",
        ],
        "field_targets": [
            "realized_volatility", "realized_variance", "volatility_regime", "jump_risk", "tail_risk",
            "risk_forecast", "dynamic_correlation", "hawkes_intensity",
        ],
        "min_strong_hits": 1,
        "min_total_hits": 2,
    },
    "order_book_order_flow_microstructure": {
        "label": "5_order_book_order_flow_microstructure",
        "strong_keywords": [
            "order book", "limit order book", "lob", "order flow", "market microstructure", "microstructure",
            "market making", "market maker", "bid-ask", "market impact", "price impact", "metaorder",
            "informed trading", "adverse selection", "signed trade", "passive order", "aggressive order",
            "queue", "order imbalance", "liquidity replenishment", "high-frequency", "hft",
        ],
        "weak_keywords": [
            "spread", "depth", "liquidity", "trade size", "execution", "fill", "auction", "cross-asset",
            "epps", "tick", "intraday", "hf",
        ],
        "field_targets": [
            "order_book_imbalance", "depth_pressure", "execution_friction", "liquidity_pressure",
            "market_impact", "order_flow_informativeness", "trade_intensity", "queue_pressure",
        ],
        "min_strong_hits": 1,
        "min_total_hits": 2,
    },
    "nonstationarity_drift_regime_control": {
        "label": "11_nonstationarity_drift_regime_control",
        "strong_keywords": [
            "non-stationary", "nonstationary", "concept drift", "distribution shift", "online learning",
            "meta-learning", "regime shift", "regime switching", "invariant", "change point",
            "structural break", "domain shift", "covariate shift", "walk-forward",
        ],
        "weak_keywords": [
            "adaptive", "regime", "robust", "calibration", "monitoring", "out-of-sample", "rolling window",
            "stability", "generalization",
        ],
        "field_targets": [
            "regime_gate", "drift_monitor", "adaptive_normalization", "robust_scaling", "stability_filter",
        ],
        "min_strong_hits": 1,
        "min_total_hits": 1,
    },
}


REJECT_RULES: dict[str, list[str]] = {
    "reject_agent_narrative_only": ["agent", "llm", "large language model", "benchmark", "capability", "closed-loop"],
    "reject_portfolio_layer_only": ["portfolio optimization", "asset allocation", "black-litterman", "mean-variance", "risk parity", "optimal portfolio", "consumption"],
    "reject_macro_or_asset_pricing_only": ["asset pricing", "factor model", "fama", "macroeconomic", "inflation", "cpi", "monetary", "capm", "q5"],
    "reject_crypto_fundamental_only": ["cryptocurrency", "crypto", "stablecoin", "bitcoin", "defi", "blockchain"],
    "reject_alt_data_unavailable": ["satellite", "alternative data", "earnings call", "supply chain", "knowledge graph", "graph neural", "gnn"],
    "reject_quantum_or_optimizer_only": ["quantum", "qaoa", "qubo", "annealing", "isotonic regression", "dynamic programming"],
    "reject_method_not_market_specific": ["treatment effect", "clinical", "drug", "screening", "baseball", "survey", "maternal"],
}


HARD_PREFILTER_REJECT_RULES: dict[str, list[str]] = {
    "reject_hard_security_bank_credit": [
        "证券", "证券市场", "证券公司", "券商", "银行", "商业银行", "央行", "存款", "贷款", "信贷", "信用风险", "债券", "保险",
        "securities", "security lending", "broker-dealer", "bank", "banks", "banking", "central bank", "depositor", "deposit", "loan", "lending",
        "credit risk", "credit valuation", "default probability", "bond", "bonds", "fixed income", "insurance",
    ],
}


LOCAL_OBSERVABLE_TERMS = [
    "return", "price", "volume", "trade", "order", "book", "depth", "spread", "bid", "ask", "liquidity",
    "volatility", "variance", "correlation", "flow", "tick", "intraday", "execution", "impact", "cost",
]

CORE_CATEGORY_KEYS = {
    "time_series_volatility_risk",
    "order_book_order_flow_microstructure",
    "nonstationarity_drift_regime_control",
}

LOCAL_MICRO_OR_VOL_TERMS = [
    "order book", "limit order book", "lob", "order flow", "market microstructure", "bid-ask", "spread",
    "depth", "queue", "market impact", "price impact", "trade", "tick", "intraday", "high-frequency",
    "volatility", "variance", "garch", "hawkes", "jump", "tail", "correlation", "covariance",
]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _contains(text: str, phrase: str) -> bool:
    phrase = phrase.lower()
    if re.fullmatch(r"[a-z0-9_+-]+", phrase):
        return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None
    return phrase in text


def _hits(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if _contains(text, keyword)]


def hard_prefilter(row: dict[str, Any]) -> dict[str, Any] | None:
    title = str(row.get("title") or "")
    summary = str(row.get("summary") or "")
    text = _normalize(f"{title}\n{summary}")
    for label, keywords in HARD_PREFILTER_REJECT_RULES.items():
        hits = _hits(text, keywords)
        if hits:
            return {
                "decision": "reject",
                "primary_label": label,
                "reason": "hard prefilter: security/bank/credit/bond/insurance topic is out of stage-1 scope",
                "hard_reject_keyword_hits": hits[:20],
                "eligible_categories": [],
                "reject_evidence": [{"label": label, "keyword_hits": hits[:20], "score": len(hits)}],
                "local_observable_hits": [],
                "micro_or_vol_hits": [],
                "requires_llm_screening": False,
            }
    return None


def classify(row: dict[str, Any]) -> dict[str, Any]:
    hard_reject = hard_prefilter(row)
    if hard_reject is not None:
        return hard_reject

    title = str(row.get("title") or "")
    summary = str(row.get("summary") or "")
    text = _normalize(f"{title}\n{summary}")
    categories: list[dict[str, Any]] = []
    for category, spec in ELIGIBLE_CATEGORIES.items():
        strong_hits = _hits(text, list(spec["strong_keywords"]))
        weak_hits = _hits(text, list(spec["weak_keywords"]))
        hits = strong_hits + [hit for hit in weak_hits if hit not in strong_hits]
        if len(strong_hits) >= int(spec["min_strong_hits"]) and len(hits) >= int(spec["min_total_hits"]):
            categories.append(
                {
                    "category": category,
                    "label": spec["label"],
                    "score": len(strong_hits) * 3 + len(weak_hits),
                    "strong_keyword_hits": strong_hits[:16],
                    "keyword_hits": hits[:16],
                    "registry_field_targets": spec["field_targets"],
                }
            )
    categories.sort(key=lambda item: int(item["score"]), reverse=True)

    reject_hits: list[dict[str, Any]] = []
    for label, keywords in REJECT_RULES.items():
        hits = _hits(text, keywords)
        if hits:
            reject_hits.append({"label": label, "keyword_hits": hits[:10], "score": len(hits)})
    reject_hits.sort(key=lambda item: int(item["score"]), reverse=True)

    observable_hits = _hits(text, LOCAL_OBSERVABLE_TERMS)
    micro_or_vol_hits = _hits(text, LOCAL_MICRO_OR_VOL_TERMS)
    core_categories = [item for item in categories if str(item["category"]) in CORE_CATEGORY_KEYS]
    hard_reject_labels = {
        "reject_agent_narrative_only",
        "reject_portfolio_layer_only",
        "reject_macro_or_asset_pricing_only",
        "reject_crypto_fundamental_only",
        "reject_alt_data_unavailable",
        "reject_quantum_or_optimizer_only",
        "reject_method_not_market_specific",
    }
    hard_reject = next((item for item in reject_hits if str(item.get("label")) in hard_reject_labels), None)
    eligible = bool(core_categories)
    if hard_reject and not core_categories:
        eligible = False
    if eligible:
        decision = "eligible"
        primary_label = core_categories[0]["label"]
        reason = "matches stage-1 4/5/11 category candidate gate; requires LLM screening"
    else:
        decision = "reject"
        primary_label = hard_reject["label"] if hard_reject else (reject_hits[0]["label"] if reject_hits else "reject_not_4_5_11")
        reason = "no stage-1 4/5/11 category signal"
        if not observable_hits:
            primary_label = "reject_no_local_observable"

    return {
        "decision": decision,
        "primary_label": primary_label,
        "reason": reason,
        "eligible_categories": categories,
        "reject_evidence": reject_hits,
        "local_observable_hits": observable_hits[:20],
        "micro_or_vol_hits": micro_or_vol_hits[:20],
        "requires_llm_screening": eligible,
    }


def build_llm_screening_payload(row: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "stage1-llm-registry-screen-v1",
        "prompt": STAGE1_LLM_PROMPT,
        "paper": {
            "arxiv_id": row.get("arxiv_id") or "",
            "title": row.get("title") or "",
            "url": row.get("url") or "",
            "source_id": row.get("source_id") or "",
            "published": row.get("published") or row.get("publish_time") or "",
            "summary": row.get("summary") or "",
        },
        "deterministic_prefilter": {
            "decision": gate.get("decision"),
            "primary_label": gate.get("primary_label"),
            "reason": gate.get("reason"),
            "eligible_categories": gate.get("eligible_categories") or [],
            "local_observable_hits": gate.get("local_observable_hits") or [],
            "micro_or_vol_hits": gate.get("micro_or_vol_hits") or [],
        },
        "llm_task": {
            "must_reject_if": [
                "证券/银行/存款/贷款/信用风险/债券/保险主题",
                "不属于 4 时间序列/波动率/风险预测、5 订单簿/订单流/微观结构、11 非平稳/漂移/regime 控制",
                "只是组合层、宏观解释、agent叙事、另类数据、量子加速或通用统计方法且不涉及 4/5/11",
            ],
            "must_keep_only_if": [
                "属于 volatility/risk/jump/tail/regime/correlation/time-series forecasting 方向",
                "属于 order_book/order_flow/liquidity/impact/queue/spread/depth/market microstructure 方向",
                "属于 nonstationarity/concept_drift/regime/adaptive/robust/walk-forward 方向",
            ],
        },
    }


def build_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = Counter(str(row.get("stage1_gate", {}).get("decision") or "unknown") for row in rows)
    labels = Counter(str(row.get("stage1_gate", {}).get("primary_label") or "unknown") for row in rows)
    category_counts: Counter[str] = Counter()
    llm_required = 0
    hard_rejects = 0
    for row in rows:
        gate = row.get("stage1_gate") if isinstance(row.get("stage1_gate"), dict) else {}
        if gate.get("requires_llm_screening"):
            llm_required += 1
        if str(gate.get("primary_label") or "").startswith("reject_hard_"):
            hard_rejects += 1
        for item in gate.get("eligible_categories") or []:
            if isinstance(item, dict):
                category_counts[str(item.get("label") or item.get("category") or "unknown")] += 1
    examples: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        gate = row.get("stage1_gate") if isinstance(row.get("stage1_gate"), dict) else {}
        label = str(gate.get("primary_label") or "unknown")
        examples.setdefault(label, [])
        if len(examples[label]) < 5:
            examples[label].append(
                {
                    "arxiv_id": str(row.get("arxiv_id") or ""),
                    "title": str(row.get("title") or ""),
                    "url": str(row.get("url") or ""),
                }
            )
    return {
        "row_count": len(rows),
        "decision_counts": dict(decisions),
        "primary_label_counts": dict(labels.most_common()),
        "eligible_category_counts": dict(category_counts.most_common()),
        "requires_llm_screening_count": llm_required,
        "hard_reject_count": hard_rejects,
        "examples_by_primary_label": examples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage-1 4/5/11 gate for arXiv papers, with hard exclusions and LLM screening input.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--llm-input-output", type=Path, default=DEFAULT_LLM_INPUT)
    parser.add_argument("--llm-prompt-output", type=Path, default=DEFAULT_LLM_PROMPT)
    parser.add_argument("--eligible-only", action="store_true", help="Write only eligible rows to output.")
    parser.add_argument("--no-llm-input", action="store_true", help="Do not write stage-1 LLM screening input JSONL.")
    args = parser.parse_args()

    rows = read_jsonl(args.input)
    out_rows: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        enriched["stage1_gate"] = classify(row)
        if args.eligible_only and enriched["stage1_gate"]["decision"] != "eligible":
            continue
        out_rows.append(enriched)

    if not args.no_llm_input:
        llm_rows = [build_llm_screening_payload(row, row["stage1_gate"]) for row in out_rows if row.get("stage1_gate", {}).get("requires_llm_screening")]
        write_jsonl(args.llm_input_output, llm_rows)
        args.llm_prompt_output.parent.mkdir(parents=True, exist_ok=True)
        args.llm_prompt_output.write_text(STAGE1_LLM_PROMPT.strip() + "\n", encoding="utf-8")

    write_jsonl(args.output, out_rows)
    report = build_report(out_rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "rows": len(out_rows), "output": str(args.output), "report": str(args.report), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())