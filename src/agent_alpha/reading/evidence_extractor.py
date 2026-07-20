from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from agent_alpha.memory.document_ingestor import EvidenceChunk
from agent_alpha.rag.field_registry import FieldRegistry


HF_TERMS = {
    "order book": ("askP1", "bidP1", "askV1", "bidV1"),
    "limit order book": ("askP1", "bidP1", "askV1", "bidV1"),
    "spread": ("askP1", "bidP1"),
    "bid": ("bidP1", "bidV1"),
    "ask": ("askP1", "askV1"),
    "depth": ("askV1", "bidV1"),
    "imbalance": ("askV1", "bidV1", "totalDeputeBuy", "totalDeputeSell"),
    "liquidity": ("volume", "money", "askV1", "bidV1"),
    "volume": ("volume",),
    "turnover": ("money",),
    "trade flow": ("volume", "money", "averageBuy", "averageSell"),
    "microstructure": ("askP1", "bidP1", "askV1", "bidV1", "volume"),
    "intraday": ("close", "volume", "money"),
    "high-frequency": ("close", "volume", "money", "askP1", "bidP1"),
    "高频": ("close", "volume", "money", "askP1", "bidP1"),
    "盘口": ("askP1", "bidP1", "askV1", "bidV1"),
    "价差": ("askP1", "bidP1"),
    "成交量": ("volume",),
    "成交额": ("money",),
    "流动性": ("volume", "money", "askV1", "bidV1"),
}

BLOCKED_TERMS = {
    "fundamental": "fundamental data",
    "earnings": "earnings",
    "revenue": "revenue",
    "analyst": "analyst data",
    "macro": "macro data",
    "news": "news data",
    "sentiment": "sentiment data",
    "industry": "industry label",
    "基本面": "fundamental data",
    "财报": "financial statement data",
    "分析师": "analyst data",
    "宏观": "macro data",
    "新闻": "news data",
    "舆情": "sentiment data",
    "行业": "industry label",
}


@dataclass(frozen=True)
class RMARecord:
    chunk_id: str
    decision: str
    reason: str
    required_fields: list[str]
    available_proxy_fields: list[str]
    mechanism_summary: str
    evidence_summary: str
    created_at: str


def extract_candidate_evidence(chunks: list[EvidenceChunk], limit: int = 8) -> list[dict[str, Any]]:
    scored: list[tuple[int, EvidenceChunk]] = []
    keywords = tuple(HF_TERMS) + tuple(BLOCKED_TERMS) + ("formula", "model", "empirical", "finding", "limitation", "公式", "实证", "结论", "限制")
    for chunk in chunks:
        lowered = chunk.text.casefold()
        score = sum(1 for keyword in keywords if keyword.casefold() in lowered)
        if score:
            scored.append((score, chunk))
    if not scored:
        scored = [(1, chunk) for chunk in chunks[:limit]]
    scored.sort(key=lambda item: item[0], reverse=True)
    evidence: list[dict[str, Any]] = []
    for index, (_, chunk) in enumerate(scored[:limit], start=1):
        quote = re.sub(r"\s+", " ", chunk.text).strip()[:500]
        evidence.append(
            {
                "evidence_id": f"ev_{index:04d}",
                "chunk_id": chunk.chunk_id,
                "quote": quote,
                "section": chunk.section,
                "page": chunk.page,
                "why_relevant": "Contains research mechanism, data, empirical setting, limitation, or high-frequency implementability cues.",
            }
        )
    return evidence


def classify_chunk_for_rma(chunk: EvidenceChunk, registry: FieldRegistry | None = None) -> RMARecord:
    registry = registry or FieldRegistry.from_yaml()
    lowered = chunk.text.casefold()
    blocked_hits = sorted({label for term, label in BLOCKED_TERMS.items() if term.casefold() in lowered})
    proxy_fields = sorted({field for term, fields in HF_TERMS.items() if term.casefold() in lowered for field in fields if field in registry.allowed_input_fields and field not in registry.label_fields})
    required_fields = blocked_hits + proxy_fields
    if blocked_hits and not proxy_fields:
        decision = "DROP"
        reason = "Chunk depends on unavailable research fields that cannot directly enter Agent Alpha high-frequency formulas."
    elif proxy_fields:
        decision = "KEEP"
        reason = "Chunk mentions a mechanism that can be represented or proxied with high-frequency whitelist fields."
        if blocked_hits:
            reason += " Non-HF fields are context only and must not enter formulas."
    else:
        decision = "DROP"
        reason = "No stable proxy in the current high-frequency field whitelist was detected."
    return RMARecord(
        chunk_id=chunk.chunk_id,
        decision=decision,
        reason=reason,
        required_fields=required_fields,
        available_proxy_fields=proxy_fields,
        mechanism_summary=re.sub(r"\s+", " ", chunk.text).strip()[:300],
        evidence_summary=f"{chunk.title} / {chunk.section}",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def build_rma_records(chunks: list[EvidenceChunk], registry: FieldRegistry | None = None) -> list[dict[str, Any]]:
    return [asdict(classify_chunk_for_rma(chunk, registry)) for chunk in chunks]