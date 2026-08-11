#!/usr/bin/env python3
"""Deduplicate parsed papers and build keyword-based topic graphs offline.

The command only reads existing new2 archives and local arXiv ``.source`` files.
It never changes the source archives or accesses an external API.
"""
from __future__ import annotations

import argparse
import gzip
import html
import io
import json
import re
import tarfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

TAXONOMY: tuple[dict[str, Any], ...] = (
    {"id": "market_microstructure", "label": "市场微观结构", "children": {
        "limit_order_book": ("限价订单簿", "limit order book", "order book", "LOB"),
        "price_discovery": ("价格发现", "price discovery", "price formation"),
        "market_making": ("做市机制", "market maker", "market making"),
        "information_asymmetry": ("信息不对称", "information asymmetry", "informed trading"),
    }},
    {"id": "order_flow", "label": "订单流与交易事件", "children": {
        "order_flow_imbalance": ("订单流不平衡", "order flow imbalance", "OFI"),
        "order_imbalance": ("委托不平衡", "order imbalance", "queue imbalance", "quote imbalance"),
        "trade_signing": ("交易方向识别", "trade sign", "signed trade", "signed volume"),
        "order_arrival_hawkes": ("订单到达与 Hawkes", "Hawkes", "order arrival", "trade arrival"),
        "order_cancellation": ("撤单与订单补充", "order cancellation", "order replenishment"),
    }},
    {"id": "liquidity_execution", "label": "流动性与交易执行", "children": {
        "bid_ask_spread": ("买卖价差", "bid-ask spread", "quoted spread", "effective spread"),
        "market_depth": ("市场深度", "market depth", "depth profile"),
        "liquidity_supply_demand": ("流动性供需", "liquidity provision", "liquidity demand", "liquidity supply"),
        "optimal_execution": ("最优执行", "optimal execution", "execution strategy"),
        "transaction_cost": ("交易成本与滑点", "transaction cost", "trading cost", "execution cost", "slippage"),
        "adverse_selection": ("逆向选择", "adverse selection", "trade toxicity", "VPIN"),
    }},
    {"id": "price_impact", "label": "市场冲击", "children": {
        "metaorder": ("Metaorder 与大额交易", "metaorder", "large order"),
        "square_root_impact": ("平方根冲击", "square-root impact", "square root impact"),
        "permanent_impact": ("永久价格冲击", "permanent impact"),
        "temporary_impact": ("临时价格冲击", "temporary impact", "transient impact"),
    }},
    {"id": "volatility_correlation", "label": "波动率与相关性", "children": {
        "realized_volatility": ("已实现波动率", "realized volatility", "realised volatility"),
        "volatility_forecasting": ("波动率预测", "volatility forecasting", "volatility prediction"),
        "volatility_jumps": ("波动率跳跃与冲击", "volatility jump", "volatility shock"),
        "rough_volatility": ("粗糙波动率", "rough volatility"),
        "high_frequency_correlation": ("高频相关性与 Epps 效应", "Epps effect", "realized correlation"),
    }},
    {"id": "return_asset_pricing", "label": "收益预测与资产定价", "children": {
        "return_prediction": ("股票收益预测", "return prediction", "stock return", "return forecast"),
        "asset_pricing_factors": ("资产定价因子", "asset pricing", "factor model", "factors"),
        "risk_premia": ("风险溢价", "risk premia", "risk premium"),
        "return_anomalies": ("异常收益", "anomaly", "abnormal return"),
        "cross_sectional_prediction": ("横截面预测", "cross-section", "cross-sectional prediction"),
    }},
    {"id": "price_volume_strategies", "label": "价量关系与交易策略", "children": {
        "short_term_momentum": ("短期动量", "short-term momentum", "momentum", "price continuation"),
        "short_term_reversal": ("短期反转", "short-term reversal", "return reversal"),
        "mean_reversion": ("均值回复", "mean reversion"),
        "price_volume": ("价量关系", "price-volume", "price volume", "volume-return"),
        "intraday_signals": ("高频交易信号", "trading signal", "intraday strategy", "technical indicator"),
    }},
    {"id": "derivatives", "label": "衍生品与金融合约", "children": {
        "options_implied_volatility": ("期权定价与隐含波动率", "option", "implied volatility", "SVI"),
        "futures_perpetuals": ("期货与永续合约", "futures", "perpetual futures"),
        "prediction_markets": ("预测市场", "prediction market"),
        "derivatives_strategies": ("衍生品策略", "derivative", "derivatives trading"),
    }},
    {"id": "portfolio_risk", "label": "组合优化与风险管理", "children": {
        "portfolio_optimization": ("组合优化", "portfolio optimization", "mean-variance", "asset allocation"),
        "portfolio_construction": ("组合构建", "portfolio construction", "portfolio choice"),
        "risk_management": ("风险管理", "risk management", "risk measure"),
        "tail_systemic_risk": ("尾部与系统性风险", "tail risk", "systemic risk", "contagion", "stress test"),
    }},
    {"id": "financial_ml", "label": "金融机器学习", "children": {
        "deep_learning_finance": ("深度学习金融应用", "deep learning", "neural network"),
        "transformer_finance": ("Transformer 与时序模型", "transformer", "attention", "temporal fusion"),
        "reinforcement_learning": ("强化学习交易", "reinforcement learning", "RL trading"),
        "llm_finance": ("大语言模型与智能体", "large language model", "LLM", "language model", "AI agent"),
        "machine_learning_prediction": ("机器学习预测", "machine learning", "predictive model"),
    }},
    {"id": "continuous_stochastic_models", "label": "连续时间与随机过程", "children": {
        "stochastic_process": ("随机过程", "stochastic process", "diffusion process"),
        "continuous_time": ("连续时间模型", "continuous time", "stochastic calculus"),
        "regime_switching": ("机制切换与隐状态", "regime switching", "hidden state", "Markov"),
        "high_order_tail": ("高阶矩与渐近", "higher moment", "skewness", "kurtosis", "asymptotic"),
    }},
    {"id": "network_spillover", "label": "网络、溢出与市场系统", "children": {
        "network_connectedness": ("网络连通性", "network", "connectedness", "centrality"),
        "spillover": ("信息溢出", "spillover", "contagion"),
        "market_simulation": ("市场模拟", "market simulation", "agent-based", "multi-agent"),
    }},
)

PARENT_RULES = tuple((item["id"], item["label"], tuple(term for child in item["children"].values() for term in child[1:])) for item in TAXONOMY)
CHILD_RULES = {item["id"]: tuple((child_id, values[0], values[1:]) for child_id, values in item["children"].items()) for item in TAXONOMY}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _arxiv_id(row: dict[str, Any]) -> str:
    value = str(row.get("arxiv_id") or row.get("id") or "").strip()
    value = re.sub(r"^arxiv:", "", value, flags=re.I)
    return value.split("v", 1)[0] if re.fullmatch(r"\d{4}\.\d{4,5}v\d+", value) else value


def _merge_rows(paths: Iterable[Path]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for path in paths:
        for row in _read_jsonl(path):
            key = _arxiv_id(row)
            if not key:
                continue
            old = merged.get(key, {})
            # Later rows may contain richer analysis, but never replace a rich
            # field with an empty value.
            combined = {**old, **{k: v for k, v in row.items() if v not in (None, "", [], {})}}
            merged[key] = combined
    return list(merged.values())


def _decode_source(payload: bytes) -> list[tuple[str, str]]:
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
            output = []
            for member in archive.getmembers():
                if not member.isfile() or member.size > 5_000_000:
                    continue
                if not member.name.lower().endswith((".tex", ".ltx", ".txt", ".tex.gz")):
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                data = stream.read(5_000_000)
                if member.name.endswith(".gz"):
                    try:
                        data = gzip.decompress(data)
                    except OSError:
                        continue
                output.append((member.name, data.decode("utf-8", errors="replace")))
            return output
    except tarfile.TarError:
        try:
            return [("source.tex", gzip.decompress(payload).decode("utf-8", errors="replace"))]
        except OSError:
            return [("source.tex", payload.decode("utf-8", errors="replace"))]


def _tex_text(source_dir: Path, arxiv_id: str) -> tuple[str, list[str]]:
    path = source_dir / f"{arxiv_id.replace('/', '_')}.source"
    if not path.exists():
        return "", []
    files = _decode_source(path.read_bytes())
    return "\n".join(text for name, text in files if not re.search(r"(^|/)(.*\.(sty|cls|bst)|README|template)", name, re.I)), [name for name, _ in files]


def _strip_tex(value: str) -> str:
    value = re.sub(r"%[^\n]*", " ", value)
    value = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^]]*\])?\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"\\[a-zA-Z@]+", " ", value)
    value = re.sub(r"[{}$^_]", " ", value)
    return " ".join(html.unescape(value).split())


def _metadata_from_tex(text: str) -> tuple[str, list[str]]:
    title_match = re.search(r"\\title\s*(?:\[[^]]*\])?\s*\{([^\n]{4,500})\}", text, re.I)
    keyword_match = re.search(r"\\(?:keywords|keyword)\s*(?:\[[^]]*\])?\s*\{([^\n]{2,1000})\}", text, re.I)
    if keyword_match is None:
        keyword_match = re.search(r"\\begin\{keywords?\}(.*?)\\end\{keywords?\}", text, re.I | re.S)
    if keyword_match is None:
        keyword_match = re.search(r"(?:keywords?|key words?)\s*:\s*([^\n]+)", text, re.I)
    title = _strip_tex(title_match.group(1)) if title_match else ""
    raw_keywords = _strip_tex(keyword_match.group(1)) if keyword_match else ""
    keywords = [item.strip().lower() for item in re.split(r"[,;]|\\and", raw_keywords) if item.strip()]
    return title, list(dict.fromkeys(keywords))


def _field_text(row: dict[str, Any]) -> str:
    note = row.get("llm_reading_note") if isinstance(row.get("llm_reading_note"), dict) else {}
    summary = row.get("structured_summary") if isinstance(row.get("structured_summary"), dict) else {}
    evidence = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
    values = [row.get("title"), note.get("central_claim"), note.get("problem"), note.get("method_logic"), summary.get("problem"), summary.get("method"), evidence.get("intro_context")]
    return " ".join(str(value or "") for value in values).lower()


def classify(row: dict[str, Any], tex_title: str = "", tex_keywords: list[str] | None = None) -> dict[str, Any]:
    keywords = list(tex_keywords or [])
    text = (_field_text(row) + " " + tex_title + " " + " ".join(keywords)).lower()
    matches: list[dict[str, Any]] = []
    for topic_id, label, rules in TOPIC_RULES:
        hits = [rule for rule in rules if rule in text]
        if hits:
            matches.append({"id": topic_id, "label_zh": label, "hits": hits, "score": len(hits)})
    matches.sort(key=lambda item: (-int(item["score"]), item["id"]))
    return {
        "primary_topic": matches[0]["id"] if matches else "other",
        "topic_labels": [item["id"] for item in matches] or ["other"],
        "topic_evidence": matches,
        "matched_terms": sorted({hit for item in matches for hit in item["hits"]}),
        "tex_title": tex_title,
        "tex_keywords": keywords,
        "classification_method": "tex_keywords_and_parsed_text" if keywords else "parsed_text_only",
        "classification_confidence": round(min(1.0, (matches[0]["score"] / 4)) if matches else 0.0, 2),
    }


def build_graphs(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        for topic in record.get("topic_labels", ["other"]):
            groups[str(topic)].append(record)
    graphs: dict[str, dict[str, Any]] = {}
    for topic, papers in groups.items():
        nodes = [{"id": f"arxiv:{p['arxiv_id']}", "title": p.get("title") or p.get("tex_title") or p["arxiv_id"], "year": p.get("year"), "role": "related", "metadata": {"topic": topic, "keywords": p.get("tex_keywords", []), "confidence": p.get("classification_confidence", 0)}} for p in papers]
        edges = []
        keyword_sets = {p["arxiv_id"]: set(p.get("tex_keywords", [])) | set(p.get("matched_terms", [])) for p in papers}
        for index, left in enumerate(papers):
            for right in papers[index + 1:]:
                shared = keyword_sets[left["arxiv_id"]].intersection(keyword_sets[right["arxiv_id"]])
                if shared:
                    edges.append({"source": f"arxiv:{left['arxiv_id']}", "target": f"arxiv:{right['arxiv_id']}", "relation": "KEYWORD_SIMILAR_TO", "weight": round(len(shared) / max(1, len(keyword_sets[left["arxiv_id"]].union(keyword_sets[right["arxiv_id"]]))), 4), "metadata": {"shared_keywords": sorted(shared)}})
        graphs[topic] = {"category": topic, "nodes": nodes, "edges": edges, "stats": {"node_count": len(nodes), "edge_count": len(edges)}}
    return graphs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="process only the first N deduplicated papers")
    args = parser.parse_args()
    rows = _merge_rows(args.input)
    if args.limit > 0:
        rows = rows[: args.limit]
    records = []
    for row in rows:
        arxiv_id = _arxiv_id(row)
        tex_title, tex_keywords = _metadata_from_tex(_tex_text(args.source_dir, arxiv_id)[0])
        classification = classify(row, tex_title, tex_keywords)
        records.append({"arxiv_id": arxiv_id, "title": row.get("title") or tex_title, "url": row.get("url") or f"https://arxiv.org/abs/{arxiv_id}", **classification})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "papers_classified.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    graphs = build_graphs(records)
    for topic, graph in graphs.items():
        (args.output_dir / f"topic_{topic}.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"paper_count": len(records), "topic_counts": dict(Counter(r["primary_topic"] for r in records)), "multi_topic_count": sum(len(r["topic_labels"]) > 1 for r in records), "tex_keyword_count": sum(bool(r["tex_keywords"]) for r in records), "graphs": {key: value["stats"] for key, value in graphs.items()}}
    (args.output_dir / "classification_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
