from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_alpha.config import project_path
from agent_alpha.memory.document_ingestor import EvidenceChunk
from agent_alpha.reading.evidence_extractor import HF_TERMS
from agent_alpha.reading.evidence_extractor import extract_candidate_evidence
from agent_alpha.reading.note_schema import ReadingNoteV1, SupportingEvidence, validate_reading_note


def _now_iso() -> str:
	return datetime.now(timezone.utc).isoformat()


def _first_match(chunks: list[EvidenceChunk], terms: tuple[str, ...], fallback: str = "输入未披露") -> str:
	for chunk in chunks:
		text = re.sub(r"\s+", " ", chunk.text).strip()
		lowered = text.casefold()
		if any(term.casefold() in lowered for term in terms):
			return text[:700]
	return fallback


def _matches(chunks: list[EvidenceChunk], terms: tuple[str, ...], limit: int = 5) -> list[str]:
	values: list[str] = []
	for chunk in chunks:
		text = re.sub(r"\s+", " ", chunk.text).strip()
		lowered = text.casefold()
		if any(term.casefold() in lowered for term in terms):
			values.append(text[:500])
		if len(values) >= limit:
			break
	return values


def _formula_blocks(chunks: list[EvidenceChunk], limit: int = 5) -> list[str]:
	formulas: list[str] = []
	for chunk in chunks:
		for formula in chunk.formula_blocks:
			cleaned = re.sub(r"\s+", " ", formula).strip()
			if cleaned and cleaned not in formulas:
				formulas.append(cleaned[:500])
			if len(formulas) >= limit:
				return formulas
	return formulas


def _score_dimensions(note_payload: dict[str, Any], chunks: list[EvidenceChunk]) -> dict[str, dict[str, Any]]:
	evidence_count = len(note_payload.get("supporting_evidence", []))
	intuition_count = len(note_payload.get("possible_trading_intuitions", []))
	mechanism_count = len(note_payload.get("mechanism_chain", []))
	text = " ".join(chunk.text for chunk in chunks).casefold()
	hf_hits = sorted({term for term in HF_TERMS if term.casefold() in text})
	formula_count = len(note_payload.get("core_formulas", []))
	empirical_count = len(note_payload.get("empirical_findings", []))
	dimensions = {
		"relevance": min(10, 3 + len(hf_hits) * 2),
		"mechanism": min(10, 3 + mechanism_count * 2 + formula_count),
		"statistical": min(10, 2 + empirical_count * 2 + (1 if note_payload.get("data_used") != "输入未披露" else 0)),
		"implementation": min(10, 2 + len(hf_hits) * 2 + formula_count),
		"cost_sensitivity": min(10, 2 + (3 if any(term in text for term in ("cost", "spread", "liquidity", "成本", "价差", "流动性")) else 0)),
		"generality": min(10, 3 + min(3, evidence_count) + min(2, intuition_count)),
	}
	return {
		key: {
			"score": score,
			"comment": "Extractive heuristic score for the existing reading gate; no factor is generated here.",
			"evidence": ", ".join(hf_hits[:8]) if hf_hits else "输入未披露",
		}
		for key, score in dimensions.items()
	}


def build_extractive_reading_note(chunks: list[EvidenceChunk], output_dir: str | Path = "data/reading_notes") -> dict[str, Any]:
	if not chunks:
		raise ValueError("cannot build reading note without evidence chunks")
	first = chunks[0]
	evidence = [SupportingEvidence(**item) for item in extract_candidate_evidence(chunks)]
	not_disclosed = []
	research_question = _first_match(chunks, ("question", "研究问题", "we study", "this paper", "本文"))
	market_setting = _first_match(chunks, ("market", "intraday", "high-frequency", "order book", "市场", "高频", "盘口"))
	data_used = _first_match(chunks, ("data", "sample", "dataset", "tick", "transaction", "数据", "样本"))
	main_mechanism = _first_match(chunks, ("mechanism", "liquidity", "imbalance", "spread", "microstructure", "机制", "流动性", "价差"))
	for field_name, value in {
		"research_question": research_question,
		"market_setting": market_setting,
		"data_used": data_used,
		"main_mechanism": main_mechanism,
	}.items():
		if value == "输入未披露":
			not_disclosed.append(field_name)
	note = ReadingNoteV1(
		schema_version="reading_note_v1",
		paper_id=first.doc_id,
		paper_title=first.title,
		source_url=first.source_url,
		source_type=first.source_type,
		research_question=research_question,
		market_setting=market_setting,
		data_used=data_used,
		main_mechanism=main_mechanism,
		mechanism_chain=_matches(chunks, ("because", "therefore", "mechanism", "lead to", "drives", "因为", "导致", "机制"), limit=5),
		core_formulas=(_formula_blocks(chunks, limit=5) + _matches(chunks, ("=", "formula", "equation", "公式", "定义为"), limit=5))[:5],
		variable_definitions=_matches(chunks, ("define", "variable", "where", "变量", "定义"), limit=5),
		empirical_findings=_matches(chunks, ("find", "result", "empirical", "significant", "发现", "结果", "显著"), limit=5),
		limitations=_matches(chunks, ("limitation", "caveat", "future work", "not", "限制", "局限"), limit=5),
		possible_trading_intuitions=_matches(chunks, ("alpha", "predict", "return", "liquidity", "imbalance", "spread", "反转", "动量", "预测"), limit=5),
		supporting_evidence=evidence,
		not_disclosed=not_disclosed,
		created_at=_now_iso(),
	)
	payload = asdict(note)
	payload["score_dimensions"] = _score_dimensions(payload, chunks)
	payload["recommendation_score"] = round(sum(float(item["score"]) for item in payload["score_dimensions"].values()) / len(payload["score_dimensions"]), 2)
	validate_reading_note(payload)
	out_dir = project_path(str(output_dir))
	out_dir.mkdir(parents=True, exist_ok=True)
	out_path = out_dir / f"{first.doc_id}.json"
	out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
	return payload

__all__ = ["build_extractive_reading_note"]