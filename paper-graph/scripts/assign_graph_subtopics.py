#!/usr/bin/env python3
"""Assign deterministic third-level labels to existing OpenAlex graph files.

This is a phase-one, metadata-only prototype: it preserves the existing graph
membership, nodes, and edges, and derives a label from seed titles using a
small TF-IDF-style vocabulary. It is intentionally offline and reproducible.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}")
STOPWORDS = {
    "about", "after", "based", "between", "from", "into", "model", "models",
    "using", "with", "for", "and", "the", "this", "that", "their", "through",
    "under", "over", "analysis", "approach", "study", "new", "via", "toward",
    "towards", "evidence", "paper", "empirical", "method", "methods", "results",
    "case", "framework", "finance", "financial", "market", "markets",
}
TOPIC_LABELS = {
    "limit_order_book": "限价订单簿",
    "asset_pricing_factors": "资产定价因子",
    "deep_learning_finance": "金融深度学习",
    "machine_learning_prediction": "机器学习预测",
    "llm_finance": "大语言模型与金融",
    "high_frequency_correlation": "高频相关性",
    "liquidity_supply_demand": "流动性供给与需求",
    "information_asymmetry": "信息不对称",
    "adverse_selection": "逆向选择",
    "bid_ask_spread": "买卖价差",
}


def tokens(text: Any) -> list[str]:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")).lower())
    return [token for token in TOKEN_RE.findall(text) if token not in STOPWORDS]


def read_graphs(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    result = []
    for path in sorted(root.glob("*/graph-*.json")):
        try:
            result.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue
    return result


def graph_seed_tokens(graph: dict[str, Any]) -> list[list[str]]:
    seed_ids = {str(value) for value in graph.get("seed_ids") or []}
    return [tokens(node.get("title")) for node in graph.get("nodes") or []
            if str(node.get("id")) in seed_ids]


def cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    numerator = sum(left[key] * right[key] for key in common)
    denominator = math.sqrt(sum(value * value for value in left.values())) * math.sqrt(
        sum(value * value for value in right.values()))
    return numerator / denominator if denominator else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--replace", action="store_true", help="replace output files if output already exists")
    args = parser.parse_args()
    if args.output_root.resolve() == args.input_root.resolve():
        raise SystemExit("output-root must differ from input-root")

    graphs = read_graphs(args.input_root)
    if not graphs:
        raise SystemExit(f"no graph files found under {args.input_root}")
    if args.output_root.exists() and not args.replace:
        raise SystemExit(f"output exists; use --replace: {args.output_root}")

    # IDF is computed within each second-level topic, so generic terms do not
    # dominate the label and each graph is compared only to its siblings.
    topic_graph_terms: dict[str, dict[str, Counter[str]]] = defaultdict(dict)
    for path, graph in graphs:
        topic = str(graph.get("topic_id") or path.parent.name)
        term_counts = Counter(token for row in graph_seed_tokens(graph) for token in row)
        topic_graph_terms[topic][str(graph.get("graph_id") or path.stem)] = term_counts

    summaries = []
    used_labels: set[str] = set()
    for path, graph in graphs:
        topic = str(graph.get("topic_id") or path.parent.name)
        graph_id = str(graph.get("graph_id") or path.stem)
        siblings = topic_graph_terms[topic]
        document_frequency = Counter(
            term for counts in siblings.values() for term in counts
        )
        own = siblings[graph_id]
        scored = []
        for term, count in own.items():
            idf = math.log((1 + len(siblings)) / (1 + document_frequency[term])) + 1
            scored.append((count * idf, term))
        scored.sort(key=lambda item: (-item[0], item[1]))
        distinctive_terms = [term for _, term in scored[:4]]
        topic_label = TOPIC_LABELS.get(topic, topic.replace("_", " ").title())
        if distinctive_terms:
            label = f"{topic_label}：{'、'.join(distinctive_terms[:2])}"
        else:
            label = f"{topic_label}：研究主题 {graph_id}"
        # Make labels unique even when two very small graphs share vocabulary.
        if label in used_labels:
            label = f"{label}（{graph_id}）"
        used_labels.add(label)

        profile = Counter()
        for term, count in own.items():
            idf = math.log((1 + len(siblings)) / (1 + document_frequency[term])) + 1
            profile[term] = count * idf
        sibling_scores = [cosine(profile, other) for key, other in siblings.items() if key != graph_id]
        coherence_values = []
        seed_profiles = [Counter(row) for row in graph_seed_tokens(graph) if row]
        for index, left in enumerate(seed_profiles):
            coherence_values.extend(cosine(left, right) for right in seed_profiles[index + 1:])
        coherence = sum(coherence_values) / len(coherence_values) if coherence_values else 1.0
        distinctiveness = 1.0 - max(sibling_scores, default=0.0)
        subtopic = {
            "id": f"{topic}_{graph_id.replace('-', '_')}",
            "label": label,
            "description": f"{topic_label}下由 {graph_id} 的固定 Seed 标题共同表征的研究方向。",
            "keywords": distinctive_terms,
            "method": "seed_title_tfidf_v1",
            "confidence": round(max(0.0, min(1.0, 0.6 * coherence + 0.4 * distinctiveness)), 4),
            "coherence": round(coherence, 4),
            "distinctiveness": round(distinctiveness, 4),
            "seed_count": len(graph.get("seed_ids") or []),
        }
        output_path = args.output_root / path.relative_to(args.input_root)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        enriched = dict(graph)
        enriched["subtopic"] = subtopic
        enriched["schema_version"] = "paper_graph_openalex_seed_subtopic_v1"
        temporary = output_path.with_name(f".{output_path.name}.tmp-{os.getpid()}")
        temporary.write_text(json.dumps(enriched, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, output_path)
        summaries.append({"topic_id": topic, "graph_id": graph_id, **subtopic})

    summary = {
        "schema_version": "paper_graph_openalex_seed_subtopic_v1",
        "source_root": str(args.input_root),
        "graph_count": len(summaries),
        "topic_count": len({row["topic_id"] for row in summaries}),
        "method": "fixed_graph_seed_title_tfidf_v1",
        "graphs": summaries,
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"graph_count": len(summaries), "topic_count": summary["topic_count"],
                      "output_root": str(args.output_root)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
