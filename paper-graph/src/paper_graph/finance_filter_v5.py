"""High-precision v5 filtering for the OpenAlex quantitative-finance corpus.

Version 4 remains available as the frozen baseline.  This profile fixes its
largest source of noise: generic method/material-science terms are useful only
when they co-occur with an authored financial-market context.  It also emits a
deterministic review priority so an LLM is never required for the full review
pool.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from paper_graph.finance_audit import (
    AMBIGUOUS_FINANCE_CONTEXTS,
    HIGH_PRECISION_TITLE_TERMS,
    NEGATIVE_CONTEXTS,
    NON_RESEARCH_WORK_TYPES,
)
from paper_graph.openalex_snapshot import QUANT_TERMS, normalize_match_text, reconstruct_abstract
from paper_graph.research_value import ResearchValueDecision


SELECTION_VERSION = "openalex_quant_prefilter_v2"
FINANCE_AUDIT_VERSION = "finance_audit_v5"
RESEARCH_VALUE_VERSION = "quant_research_value_v2"

# These words have large, well-known non-financial senses.  They are never a
# v5 candidate by themselves, regardless of whether OpenAlex put them in a
# title, abstract, keyword or topic.
WEAK_QUANT_TERMS = {
    "backtesting", "intraday", "machine learning", "microstructure",
    "out of sample", "walk forward",
}

METHOD_ALIASES = {
    "machine learning": ("machine learning", "机器学习", "aprendizaje automático", "apprentissage automatique", "pembelajaran mesin"),
    "deep learning": ("deep learning", "深度学习", "aprendizaje profundo", "apprentissage profond", "pembelajaran mendalam"),
    "reinforcement learning": ("reinforcement learning", "强化学习", "aprendizaje por refuerzo", "apprentissage par renforcement"),
    "neural network": ("neural network", "neural networks", "神经网络", "red neuronal", "réseau neuronal"),
    "sequence model": ("lstm", "long short term memory", "gru", "transformer", "autoencoder", "multilayer perceptron"),
    "tree ensemble": ("random forest", "gradient boosting", "xgboost", "lightgbm"),
    "statistical learning": ("support vector machine", "semi supervised", "sentiment analysis"),
    "econometric": ("econometric", "econometrics", "计量经济", "econométrie", "econometría"),
}

# Canonical context -> authored aliases.  The non-English list is deliberately
# compact and high precision; it can be extended without changing the scoring
# model.  CJK aliases use substring matching because word boundaries are not
# represented by spaces.
FINANCE_CONTEXT_ALIASES = {
    "algorithmic trading": ("algorithmic trading", "quantitative trading", "algo trading", "算法交易", "量化交易"),
    "asset pricing": ("asset pricing", "资产定价", "valoración de activos", "évaluation des actifs"),
    "foreign exchange": ("foreign exchange", "forex", "exchange rate", "外汇", "taux de change", "tipo de cambio"),
    "futures market": ("futures market", "futures trading", "期货市场", "期货交易"),
    "high frequency trading": ("high frequency trading", "high frequency data", "高频交易", "高频数据"),
    "market microstructure": ("market microstructure", "financial market microstructure", "市场微观结构", "microstructure du marché", "microestructura de mercado"),
    "portfolio management": ("portfolio management", "portfolio optimization", "investment portfolio", "投资组合", "gestion de portefeuille", "gestión de cartera"),
    "stock market": ("stock market", "equity market", "stock exchange", "stock index", "股票市场", "证券市场", "marché boursier", "mercado de valores", "pasar saham"),
    "stock price": ("stock price", "share price", "股票价格", "股价", "cours de l action", "precio de las acciones", "harga saham"),
    "stock return": ("stock return", "equity return", "abnormal return", "股票收益", "rendement boursier", "retorno de acciones"),
    "trade execution": ("trade execution", "order execution", "交易执行", "exécution des ordres", "ejecución de órdenes"),
    "trading strategy": ("trading strategy", "investment strategy", "trading signal", "交易策略", "投资策略", "stratégie de trading", "estrategia de trading"),
}

QUANT_ALIASES = {
    "limit order book": ("limit order book", "限价订单簿", "carnet d ordres à cours limité", "libro de órdenes límite"),
    "order book": ("order book", "订单簿", "委托簿", "carnet d ordres", "libro de órdenes"),
    "order flow": ("order flow", "订单流", "flux d ordres", "flujo de órdenes"),
    "order flow imbalance": ("order flow imbalance", "order imbalance", "订单流不平衡", "déséquilibre des ordres", "desequilibrio de órdenes"),
    "price discovery": ("price discovery", "价格发现", "découverte des prix", "descubrimiento de precios"),
    "price impact": ("price impact", "价格冲击", "impact sur les prix", "impacto en el precio"),
    "market impact": ("market impact", "市场冲击", "impact de marché", "impacto de mercado"),
    "market liquidity": ("market liquidity", "stock liquidity", "股票流动性", "市场流动性", "liquidité du marché", "liquidez de mercado", "likuiditas saham"),
    "bid ask spread": ("bid ask spread", "买卖价差", "écart acheteur vendeur", "diferencial de compra venta"),
    "optimal execution": ("optimal execution", "最优执行", "exécution optimale", "ejecución óptima"),
    "realized volatility": ("realized volatility", "已实现波动率", "volatilité réalisée", "volatilidad realizada"),
}

CORE_VALUE_TERMS = {
    "bid ask spread", "limit order book", "market impact", "market microstructure",
    "optimal execution", "order book", "order flow", "order flow imbalance",
    "price discovery", "price impact", "realized volatility",
}
STRATEGY_VALUE_TERMS = {
    "algorithmic trading", "asset pricing", "foreign exchange", "mean reversion",
    "momentum", "portfolio management", "portfolio optimization", "trading strategy",
}
RIGOR_VALUE_TERMS = {
    "backtest", "changepoint", "cross validation", "garch", "har rv", "high frequency",
    "jump", "out of sample", "reinforcement learning", "sharpe", "walk forward",
}
EMPIRICAL_VALUE_TERMS = {
    "ablation", "benchmark", "empirical", "transaction data", "tick data",
    "robustness", "statistical significance",
}
LOW_VALUE_PATTERNS = {
    "advisory chatbot", "chatbot service", "comparison of machine learning models",
    "stock price prediction system", "tutorial", "textbook",
}


@dataclass(frozen=True)
class FinanceAuditV5Decision:
    status: str
    reasons: tuple[str, ...]
    finance_anchors: tuple[str, ...] = ()
    negative_contexts: tuple[str, ...] = ()
    acceptance_score: int = 0
    authored_match_fields: tuple[str, ...] = ()
    review_priority: str = "none"
    review_priority_score: int = 0
    audit_version: str = FINANCE_AUDIT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _display_names(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return " ".join(
        str(item.get("display_name") or "")
        for item in value
        if isinstance(item, Mapping)
    )


def _field_texts(work: Mapping[str, Any]) -> dict[str, str]:
    primary_topic = work.get("primary_topic")
    primary_name = str(primary_topic.get("display_name") or "") if isinstance(primary_topic, Mapping) else ""
    return {
        "title": normalize_match_text(work.get("title") or work.get("display_name") or ""),
        "abstract": normalize_match_text(reconstruct_abstract(work.get("abstract_inverted_index"))),
        "keyword": normalize_match_text(_display_names(work.get("keywords"))),
        "topic": normalize_match_text(f"{_display_names(work.get('topics'))} {primary_name}"),
    }


def _contains(text: str, phrase: str) -> bool:
    normalized = normalize_match_text(phrase)
    if not normalized:
        return False
    if any("\u3400" <= char <= "\u9fff" for char in normalized):
        return normalized in text
    return f" {normalized} " in f" {text} "


def _find(text: str, aliases: Mapping[str, Iterable[str]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    canonical: set[str] = set()
    evidence: set[str] = set()
    for name, values in aliases.items():
        for alias in values:
            if _contains(text, alias):
                canonical.add(normalize_match_text(name))
                evidence.add(normalize_match_text(alias))
    return tuple(sorted(canonical)), tuple(sorted(evidence))


def _base_quant_aliases() -> dict[str, tuple[str, ...]]:
    aliases: dict[str, set[str]] = {}
    for term in QUANT_TERMS:
        canonical = normalize_match_text(term)
        aliases.setdefault(canonical, set()).add(term)
    for canonical, values in QUANT_ALIASES.items():
        aliases.setdefault(normalize_match_text(canonical), set()).update(values)
    return {key: tuple(sorted(values)) for key, values in aliases.items()}


BASE_QUANT_ALIASES = _base_quant_aliases()


def classify_quant_work_v2(work: Mapping[str, Any], *, threshold: int = 4) -> dict[str, Any]:
    """Classify a Work while suppressing unpaired generic-method noise."""
    texts = _field_texts(work)
    quant: dict[str, tuple[str, ...]] = {}
    aliases: dict[str, tuple[str, ...]] = {}
    methods: dict[str, tuple[str, ...]] = {}
    contexts: dict[str, tuple[str, ...]] = {}
    for field, text in texts.items():
        quant[field], aliases[field] = _find(text, BASE_QUANT_ALIASES)
        methods[field], _ = _find(text, METHOD_ALIASES)
        contexts[field], _ = _find(text, FINANCE_CONTEXT_ALIASES)

    authored_quant = set(quant["title"]) | set(quant["abstract"])
    metadata_quant = set(quant["keyword"]) | set(quant["topic"])
    authored_methods = set(methods["title"]) | set(methods["abstract"])
    authored_contexts = set(contexts["title"]) | set(contexts["abstract"])
    strong_authored = authored_quant - WEAK_QUANT_TERMS
    strong_metadata = metadata_quant - WEAK_QUANT_TERMS

    if strong_authored:
        retrieval_tier = "strong"
        reasons = tuple(f"authored_quant:{term}" for term in sorted(strong_authored))
    elif authored_contexts and (authored_methods or authored_quant & WEAK_QUANT_TERMS):
        retrieval_tier = "contextual"
        reasons = tuple(f"authored_finance_context:{term}" for term in sorted(authored_contexts))
    elif strong_metadata:
        retrieval_tier = "metadata"
        reasons = tuple(f"metadata_quant:{term}" for term in sorted(strong_metadata))
    else:
        retrieval_tier = "weak"
        weak = authored_quant | metadata_quant | authored_methods
        reasons = tuple(f"unpaired_weak_term:{term}" for term in sorted(weak)) or ("no_quant_evidence",)

    score = (
        4 * len(set(quant["title"]))
        + 3 * len(set(quant["keyword"]))
        + 2 * len(set(quant["topic"]))
        + len(set(quant["abstract"]))
        + 3 * len(set(contexts["title"]))
        + 2 * len(set(methods["title"]))
    )
    result: dict[str, Any] = {
        "is_quant_candidate": retrieval_tier != "weak",
        "is_weak_candidate": retrieval_tier == "weak",
        "passes_score_threshold": score >= threshold and retrieval_tier != "weak",
        "quant_score": score,
        "retrieval_tier": retrieval_tier,
        "retrieval_reasons": list(reasons),
        "threshold": threshold,
        "selection_version": SELECTION_VERSION,
    }
    for field in texts:
        result[f"matched_{field}_terms"] = list(quant[field])
        result[f"matched_{field}_aliases"] = list(aliases[field])
        result[f"matched_{field}_method_terms"] = list(methods[field])
        result[f"matched_{field}_finance_contexts"] = list(contexts[field])
    return result


def _set(match: Mapping[str, Any], key: str) -> set[str]:
    return {normalize_match_text(value) for value in match.get(key, []) if normalize_match_text(value)}


def _phrases(text: str, vocabulary: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(term for term in vocabulary if _contains(text, term)))


def audit_finance_context_v5(work: Mapping[str, Any], match: Mapping[str, Any]) -> FinanceAuditV5Decision:
    """Audit a v2 retrieval decision with deterministic review prioritisation."""
    texts = _field_texts(work)
    all_text = " ".join(texts.values())
    negatives = _phrases(all_text, NEGATIVE_CONTEXTS)
    ambiguous = _phrases(all_text, AMBIGUOUS_FINANCE_CONTEXTS)
    title_hits = _set(match, "matched_title_terms")
    abstract_hits = _set(match, "matched_abstract_terms")
    metadata_hits = _set(match, "matched_keyword_terms") | _set(match, "matched_topic_terms")
    title_methods = _set(match, "matched_title_method_terms")
    abstract_methods = _set(match, "matched_abstract_method_terms")
    title_contexts = _set(match, "matched_title_finance_contexts")
    abstract_contexts = _set(match, "matched_abstract_finance_contexts")
    contexts = tuple(sorted(title_contexts | abstract_contexts))
    authored_fields = tuple(
        field for field, hits in (
            ("title", title_hits | title_methods), ("abstract", abstract_hits | abstract_methods)
        ) if hits
    )
    work_type = normalize_match_text(work.get("type") or "")
    if work_type in NON_RESEARCH_WORK_TYPES:
        return FinanceAuditV5Decision(
            "rejected", (f"non_research_work_type:{work_type}",),
            authored_match_fields=authored_fields,
        )
    if match.get("retrieval_tier") == "weak" or not match.get("is_quant_candidate", False):
        return FinanceAuditV5Decision(
            "rejected", ("weak_retrieval_without_authored_finance_context",),
            authored_match_fields=authored_fields,
        )

    strong_title = title_hits - WEAK_QUANT_TERMS
    strong_abstract = abstract_hits - WEAK_QUANT_TERMS
    high_precision_title = strong_title & (set(HIGH_PRECISION_TITLE_TERMS) | CORE_VALUE_TERMS)
    method_with_context = bool((title_methods | abstract_methods) and contexts)
    score = 0
    score += 6 if strong_title else 0
    score += 4 if strong_abstract else 0
    score += 3 if title_contexts else 0
    score += 2 if abstract_contexts else 0
    score += 3 if method_with_context else 0
    score += 1 if len(title_hits | abstract_hits | title_methods | abstract_methods) >= 2 else 0
    common = {
        "acceptance_score": score,
        "authored_match_fields": authored_fields,
        "finance_anchors": tuple(sorted(set(contexts) | strong_title | strong_abstract)),
    }
    if negatives and not contexts:
        return FinanceAuditV5Decision(
            "rejected", tuple(f"negative_context:{term}" for term in negatives),
            negative_contexts=negatives, **common,
        )
    if negatives:
        return FinanceAuditV5Decision(
            "review", ("conflicting_finance_and_negative_context",),
            negative_contexts=negatives, review_priority="medium", review_priority_score=4, **common,
        )
    if ambiguous and not high_precision_title:
        return FinanceAuditV5Decision(
            "review", tuple(f"ambiguous_finance_context:{term}" for term in ambiguous),
            review_priority="low", review_priority_score=2, **common,
        )
    if not (title_hits or abstract_hits or title_methods or abstract_methods) and metadata_hits:
        return FinanceAuditV5Decision(
            "review", ("metadata_only_quant_match",),
            review_priority="low", review_priority_score=1, **common,
        )

    has_local_evidence = bool(
        texts["abstract"] or work.get("referenced_works")
        or work.get("referenced_works_count") or work.get("cited_by_count")
    )
    if high_precision_title:
        return FinanceAuditV5Decision(
            "accepted", tuple(f"high_precision_quant_title:{term}" for term in sorted(high_precision_title)),
            **common,
        )
    if title_methods and title_contexts:
        return FinanceAuditV5Decision(
            "accepted", tuple(f"method_with_title_finance_context:{term}" for term in sorted(title_methods)),
            **common,
        )
    if abstract_methods and title_contexts and has_local_evidence:
        return FinanceAuditV5Decision(
            "accepted", tuple(f"method_abstract_with_title_finance_context:{term}" for term in sorted(abstract_methods)),
            **common,
        )
    if strong_title and title_contexts and (has_local_evidence or score >= 9):
        return FinanceAuditV5Decision(
            "accepted", tuple(f"quant_title_with_finance_context:{term}" for term in sorted(strong_title)),
            **common,
        )
    # Broad phrases such as information asymmetry, transaction costs and
    # liquidity risk also describe supply chains, public policy and corporate
    # finance.  Evidence volume alone cannot turn them into market research;
    # they remain prioritised review unless the title supplies a market object.
    if strong_abstract and title_contexts and score >= 7:
        return FinanceAuditV5Decision(
            "accepted", tuple(f"quant_abstract_with_title_finance_context:{term}" for term in sorted(strong_abstract)),
            **common,
        )

    priority_score = 0
    priority_score += 4 if title_contexts else 0
    priority_score += 3 if strong_title else 0
    priority_score += 2 if strong_abstract else 0
    priority_score += 2 if method_with_context else 0
    priority_score += 1 if has_local_evidence else 0
    priority = "high" if priority_score >= 7 else "medium" if priority_score >= 4 else "low"
    return FinanceAuditV5Decision(
        "review", ("relevant_evidence_below_v5_acceptance_threshold",),
        review_priority=priority, review_priority_score=priority_score, **common,
    )


def _text_hits(text: str, terms: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(term for term in terms if _contains(text, term)))


def assess_research_value_v2(
    work: Mapping[str, Any], finance: FinanceAuditV5Decision
) -> ResearchValueDecision:
    """Score accepted research while avoiding citation-age as a hard gate."""
    work_type = normalize_match_text(work.get("type") or "")
    if work_type in NON_RESEARCH_WORK_TYPES or finance.status == "rejected":
        return ResearchValueDecision("exclude", 0, (f"finance_status:{finance.status}",), RESEARCH_VALUE_VERSION)
    if finance.status != "accepted":
        reasons = [f"finance_status:{finance.status}"]
        if finance.review_priority != "none":
            reasons.append(f"review_priority:{finance.review_priority}")
        return ResearchValueDecision("unknown", finance.review_priority_score, tuple(reasons), RESEARCH_VALUE_VERSION)

    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    text = normalize_match_text(f"{work.get('title') or ''} {abstract}")
    core = _text_hits(text, CORE_VALUE_TERMS)
    strategy = _text_hits(text, STRATEGY_VALUE_TERMS)
    rigor = _text_hits(text, RIGOR_VALUE_TERMS)
    empirical = _text_hits(text, EMPIRICAL_VALUE_TERMS)
    low = _text_hits(text, LOW_VALUE_PATTERNS)
    has_references = bool(work.get("referenced_works") or work.get("referenced_works_count"))
    has_exact_identity = bool(work.get("arxiv_id") or work.get("doi"))
    score = 0
    reasons: list[str] = []
    for hits, points, label in (
        (core, 4, "core"), (strategy, 3, "strategy"),
        (rigor, 2, "rigor"), (empirical, 1, "empirical"),
    ):
        if hits:
            score += points
            reasons.extend(f"{label}:{term}" for term in hits)
    if abstract:
        score += 1
        reasons.append("has_abstract")
    if has_references:
        score += 1
        reasons.append("has_references")
    if has_exact_identity:
        score += 1
        reasons.append("has_exact_external_identity")
    if low:
        score -= 3
        reasons.extend(f"low_value_pattern:{term}" for term in low)

    if (core and score >= 5) or (strategy and rigor and score >= 6):
        tier = "high"
    elif score >= 4:
        tier = "medium"
    else:
        tier = "low"
    return ResearchValueDecision(tier, score, tuple(reasons or ("limited_value_evidence",)), RESEARCH_VALUE_VERSION)


__all__ = [
    "FINANCE_AUDIT_VERSION", "RESEARCH_VALUE_VERSION", "SELECTION_VERSION",
    "FinanceAuditV5Decision", "assess_research_value_v2",
    "audit_finance_context_v5", "classify_quant_work_v2",
]
