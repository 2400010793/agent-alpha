from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from agent_alpha.llm.client import LLMClient
from agent_alpha.llm.prompt_runner import load_prompt, run_json_prompt
from agent_alpha.reading.evidence_pack import build_evidence_pack_v2, build_reading_tasks_from_evidence_pack
from agent_alpha.reading.note_schema import validate_reading_note
from agent_alpha.signals.reading_gate import SCORE_DIMENSIONS


REQUIRED_NOTE_FIELDS = (
    "schema_version",
    "paper_id",
    "paper_title",
    "source_url",
    "source_type",
    "research_question",
    "market_setting",
    "data_used",
    "main_mechanism",
    "mechanism_chain",
    "core_formulas",
    "variable_definitions",
    "empirical_findings",
    "limitations",
    "possible_trading_intuitions",
    "supporting_evidence",
    "not_disclosed",
    "score_dimensions",
    "recommendation_score",
    "created_at",
)

CHUNK_TASKS = (
    "overview_claims",
    "formula_variables",
    "method_data_results",
    "experimental_code",
    "conclusion_limits",
)

TASK_KEYWORDS = {
    "overview_claims": ("abstract", "introduction", "motivation", "problem", "contribution", "claim"),
    "formula_variables": ("formula", "equation", "model", "define", "definition", "variable", "where", "公式", "变量"),
    "method_data_results": ("method", "data", "sample", "empirical", "experiment", "result", "regression", "robust", "数据", "实证", "结果"),
    "experimental_code": ("algorithm", "implementation", "code", "simulation", "procedure", "estimator", "实验", "算法"),
    "conclusion_limits": ("conclusion", "discussion", "limitation", "future", "caveat", "cost", "capacity", "结论", "限制", "局限"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chunk_dict(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, dict):
        return chunk
    if hasattr(chunk, "__dict__"):
        return dict(chunk.__dict__)
    raise TypeError(f"unsupported chunk type: {type(chunk).__name__}")


def _compact_chunks(chunks: list[dict[str, Any]], max_chunks: int) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for chunk in chunks[:max_chunks]:
        compact.append(
            {
                "chunk_id": chunk.get("chunk_id", ""),
                "doc_id": chunk.get("doc_id", ""),
                "source_type": chunk.get("source_type", ""),
                "source_format": chunk.get("source_format", ""),
                "source_url": chunk.get("source_url", ""),
                "title": chunk.get("title", ""),
                "authors": chunk.get("authors", []),
                "published_at": chunk.get("published_at", ""),
                "section": chunk.get("section", ""),
                "page": chunk.get("page"),
                "text": str(chunk.get("text", ""))[:2400],
                "formula_blocks": chunk.get("formula_blocks", [])[:5] if isinstance(chunk.get("formula_blocks", []), list) else [],
                "table_captions": chunk.get("table_captions", [])[:3] if isinstance(chunk.get("table_captions", []), list) else [],
                "figure_captions": chunk.get("figure_captions", [])[:3] if isinstance(chunk.get("figure_captions", []), list) else [],
            }
        )
    return compact


def _chunk_text(chunk: dict[str, Any]) -> str:
    values = [chunk.get("section", ""), chunk.get("text", "")]
    values.extend(chunk.get("formula_blocks", []) if isinstance(chunk.get("formula_blocks"), list) else [])
    values.extend(chunk.get("table_captions", []) if isinstance(chunk.get("table_captions"), list) else [])
    values.extend(chunk.get("figure_captions", []) if isinstance(chunk.get("figure_captions"), list) else [])
    return "\n".join(str(value) for value in values).casefold()


def _score_chunk_for_task(chunk: dict[str, Any], task: str) -> int:
    text = _chunk_text(chunk)
    score = sum(3 for keyword in TASK_KEYWORDS.get(task, ()) if keyword.casefold() in text)
    section = str(chunk.get("section", "")).casefold()
    if task == "formula_variables" and chunk.get("formula_blocks"):
        score += 8
    if task == "method_data_results" and re.search(r"\b(table|figure|result|empirical|sample|data)\b", text):
        score += 4
    if task == "overview_claims" and any(name in section for name in ("abstract", "introduction", "overview")):
        score += 8
    if task == "conclusion_limits" and any(name in section for name in ("conclusion", "discussion", "limitation")):
        score += 8
    return score


def select_reading_chunks(chunks: list[dict[str, Any]], *, max_chunks: int = 32) -> list[dict[str, Any]]:
    """Select high-value chunks using new2-style reading tasks before LLM calls."""
    if max_chunks <= 0:
        return []
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    per_task = max(2, max_chunks // len(CHUNK_TASKS))
    for task in CHUNK_TASKS:
        ranked = sorted(chunks, key=lambda chunk: _score_chunk_for_task(chunk, task), reverse=True)
        picked = 0
        for chunk in ranked:
            chunk_id = str(chunk.get("chunk_id") or "")
            if not chunk_id or chunk_id in seen or _score_chunk_for_task(chunk, task) <= 0:
                continue
            selected.append({**chunk, "reading_task": task})
            seen.add(chunk_id)
            picked += 1
            if picked >= per_task or len(selected) >= max_chunks:
                break
        if len(selected) >= max_chunks:
            break
    if len(selected) < max_chunks:
        for chunk in chunks:
            chunk_id = str(chunk.get("chunk_id") or "")
            if chunk_id and chunk_id not in seen:
                selected.append({**chunk, "reading_task": "supplemental"})
                seen.add(chunk_id)
            if len(selected) >= max_chunks:
                break
    return selected[:max_chunks]


def _meta_from_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    first = chunks[0]
    return {
        "paper_id": first.get("doc_id", ""),
        "paper_title": first.get("title", ""),
        "source_url": first.get("source_url", ""),
        "source_type": first.get("source_type", ""),
        "authors": first.get("authors", []),
        "published_at": first.get("published_at", ""),
    }


def _paper_meta_for_tasks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    meta = _meta_from_chunks(chunks)
    return {
        "paper_id": meta.get("paper_id", ""),
        "title": meta.get("paper_title", ""),
        "url": meta.get("source_url", ""),
        "source_type": meta.get("source_type", ""),
        "authors": meta.get("authors", []),
        "published_at": meta.get("published_at", ""),
    }


def _ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _normalize_score_dimensions(value: Any) -> dict[str, dict[str, Any]]:
    raw = value if isinstance(value, dict) else {}
    normalized: dict[str, dict[str, Any]] = {}
    for key in SCORE_DIMENSIONS:
        item = raw.get(key, {}) if isinstance(raw.get(key, {}), dict) else {}
        try:
            score = float(item.get("score", 1))
        except (TypeError, ValueError):
            score = 1.0
        normalized[key] = {
            "score": max(1.0, min(10.0, score)),
            "comment": str(item.get("comment") or "输入未披露"),
            "evidence": str(item.get("evidence") or "输入未披露"),
            "critique": str(item.get("critique") or "输入未披露"),
        }
    return normalized


def _is_missing_score_dimensions(dimensions: dict[str, dict[str, Any]]) -> bool:
    return all(float(item.get("score", 0) or 0) <= 1.0 for item in dimensions.values())


def _chunk_note_text_items(chunk_note: dict[str, Any]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for key in (
        "central_claims",
        "problem_or_context",
        "method_logic",
        "core_formulas",
        "experimental_formulas",
        "code_or_algorithm_logic",
        "variable_definitions",
        "data_and_empirical_setup",
        "key_results",
        "conclusion_claims",
        "limitations",
    ):
        for value in _ensure_list(chunk_note.get(key)):
            text = re.sub(r"\s+", " ", str(value)).strip()
            if text and text != "输入未披露":
                items.append((key, text[:700]))
    return items


def _fallback_supporting_evidence(chunk_notes: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for chunk_note in chunk_notes or []:
        chunk_id = str(chunk_note.get("chunk_id") or "")
        if not chunk_id:
            continue
        for key, text in _chunk_note_text_items(chunk_note):
            evidence.append(
                {
                    "evidence_id": f"ev_{len(evidence) + 1:04d}",
                    "chunk_id": chunk_id,
                    "quote": text,
                    "section": str(chunk_note.get("reading_task") or chunk_id),
                    "page": None,
                    "why_relevant": f"Fallback evidence from reading_note_chunk_v1 field {key}.",
                }
            )
            if len(evidence) >= 8:
                return evidence
    return evidence


def _fallback_score_dimensions(note: dict[str, Any], chunk_notes: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    evidence_count = len(note.get("supporting_evidence", []))
    mechanism_count = len(note.get("mechanism_chain", []))
    intuition_count = len(note.get("possible_trading_intuitions", []))
    formula_count = len(note.get("core_formulas", []))
    empirical_count = len(note.get("empirical_findings", []))
    chunk_text = " ".join(
        text
        for chunk_note in (chunk_notes or [])
        for _, text in _chunk_note_text_items(chunk_note)
    ).casefold()
    has_cost_context = any(term in chunk_text for term in ("cost", "transaction cost", "spread", "liquidity", "成本", "价差", "流动性"))
    score_values = {
        "relevance": 7 if evidence_count and intuition_count else 5 if evidence_count else 3,
        "mechanism": 7 if mechanism_count and formula_count else 6 if mechanism_count else 3,
        "statistical": 5 if empirical_count else 3,
        "implementation": 6 if formula_count or intuition_count else 4,
        "cost_sensitivity": 5 if has_cost_context else 3,
        "generality": 6 if mechanism_count and evidence_count else 4,
    }
    return {
        key: {
            "score": float(score),
            "comment": "Fallback score derived from chunk notes because LLM merge omitted usable score_dimensions.",
            "evidence": "supporting_evidence" if evidence_count else "输入未披露",
            "critique": "Heuristic fallback; rerun with stricter LLM scoring prompt for final research use.",
        }
        for key, score in score_values.items()
    }


def _normalize_note(raw_note: dict[str, Any], chunks: list[dict[str, Any]], *, chunk_notes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    meta = _meta_from_chunks(chunks)
    note = dict(raw_note)
    note["schema_version"] = "reading_note_v1"
    note["paper_id"] = str(note.get("paper_id") or meta["paper_id"])
    note["paper_title"] = str(note.get("paper_title") or meta["paper_title"])
    note["source_url"] = str(note.get("source_url") or meta["source_url"])
    note["source_type"] = str(note.get("source_type") or meta["source_type"])
    for key in ("research_question", "market_setting", "data_used", "main_mechanism"):
        note[key] = str(note.get(key) or "输入未披露")
    for key in ("mechanism_chain", "core_formulas", "variable_definitions", "empirical_findings", "limitations", "possible_trading_intuitions", "not_disclosed"):
        note[key] = [str(item) for item in _ensure_list(note.get(key))]
    evidence = []
    for index, item in enumerate(_ensure_list(note.get("supporting_evidence")), start=1):
        if not isinstance(item, dict):
            continue
        evidence.append(
            {
                "evidence_id": str(item.get("evidence_id") or f"ev_{index:04d}"),
                "chunk_id": str(item.get("chunk_id") or ""),
                "quote": str(item.get("quote") or "输入未披露"),
                "section": str(item.get("section") or ""),
                "page": item.get("page"),
                "why_relevant": str(item.get("why_relevant") or "输入未披露"),
            }
        )
    if not evidence:
        evidence = _fallback_supporting_evidence(chunk_notes)
    note["supporting_evidence"] = evidence
    for key in ("sample", "formula", "cost", "out_of_sample"):
        if key not in note["not_disclosed"] and "输入未披露" in str(note.get(key, "")):
            note["not_disclosed"].append(key)
    note["score_dimensions"] = _normalize_score_dimensions(note.get("score_dimensions"))
    if _is_missing_score_dimensions(note["score_dimensions"]):
        note["score_dimensions"] = _fallback_score_dimensions(note, chunk_notes)
    note["recommendation_score"] = round(sum(float(item["score"]) for item in note["score_dimensions"].values()) / len(SCORE_DIMENSIONS), 2)
    note["created_at"] = str(note.get("created_at") or _now_iso())
    validate_reading_note(note)
    return {key: note[key] for key in REQUIRED_NOTE_FIELDS}


def _chunk_note_schema(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "reading_note_chunk_v1",
        "chunk_id": chunk.get("chunk_id", ""),
        "reading_task": chunk.get("reading_task", chunk.get("chunk_id", "")),
        "central_claims": [],
        "problem_or_context": [],
        "method_logic": [],
        "core_formulas": [],
        "experimental_formulas": [],
        "code_or_algorithm_logic": [],
        "variable_definitions": [],
        "data_and_empirical_setup": [],
        "key_results": [],
        "conclusion_claims": [],
        "limitations": [],
        "not_disclosed": [],
        "faithfulness_constraints_for_next_llm": [],
    }


def build_chunk_reading_note(chunk: dict[str, Any], client: LLMClient) -> dict[str, Any]:
    system_prompt = (
        "You are Agent Alpha AI-1 chunk reader. Read only the current chunk and produce reading_note_chunk_v1 JSON. "
        "Do not generate signals, factors, or Python code. Do not use information not present in this chunk. "
        "If sample, formula, cost, out-of-sample, robustness, or capacity is not disclosed, write 输入未披露."
    )
    payload_chunk = _compact_chunks([chunk], max_chunks=1)[0] if "text" in chunk else chunk
    payload = {"chunk": payload_chunk, "required_schema": _chunk_note_schema(chunk)}
    note = run_json_prompt(
        client,
        system_prompt=system_prompt,
        user_payload=json.dumps(payload, ensure_ascii=False),
        task_name="paper_reading_chunk_v1",
    )
    note.setdefault("schema_version", "reading_note_chunk_v1")
    note.setdefault("chunk_id", chunk.get("chunk_id", ""))
    note.setdefault("reading_task", chunk.get("reading_task", ""))
    return note


def merge_chunk_reading_notes(chunks: list[dict[str, Any]], chunk_notes: list[dict[str, Any]], client: LLMClient) -> dict[str, Any]:
    system_prompt = load_prompt("prompts/paper_reading/reading_note_v1_system.md") + "\n\nMerge only the supplied reading_note_chunk_v1 records into one reading_note_v1. Do not introduce evidence absent from chunk notes."
    payload = {
        "paper_meta": _meta_from_chunks(chunks),
        "chunk_notes": chunk_notes,
        "required_fields": list(REQUIRED_NOTE_FIELDS),
        "score_dimensions": list(SCORE_DIMENSIONS),
        "not_disclosed_text": "输入未披露",
        "forbidden_outputs": ["alpha_signal", "factor", "factor_expression", "python_code"],
    }
    raw_note = run_json_prompt(
        client,
        system_prompt=system_prompt,
        user_payload=json.dumps(payload, ensure_ascii=False),
        task_name="paper_reading_merge_v1",
    )
    return _normalize_note(raw_note, chunks, chunk_notes=chunk_notes)


def build_llm_reading_note(
    chunks: list[dict[str, Any]],
    client: LLMClient,
    *,
    max_chunks: int = 8,
    chunked: bool = False,
) -> dict[str, Any]:
    """Build a faithful reading_note_v1 from evidence chunks using an LLM."""
    chunk_dicts = [_chunk_dict(chunk) for chunk in chunks]
    if not chunk_dicts:
        raise ValueError("cannot build LLM reading note without chunks")
    if chunked:
        evidence_pack = build_evidence_pack_v2(chunk_dicts)
        reading_tasks = build_reading_tasks_from_evidence_pack(evidence_pack, _paper_meta_for_tasks(chunk_dicts))
        chunk_notes = [build_chunk_reading_note(task, client) for task in reading_tasks]
        return merge_chunk_reading_notes(chunk_dicts, chunk_notes, client)
    selected_chunks = select_reading_chunks(chunk_dicts, max_chunks=max_chunks)
    compact_chunks = _compact_chunks(selected_chunks, max_chunks=max_chunks)
    system_prompt = load_prompt("prompts/paper_reading/reading_note_v1_system.md")
    payload = {
        "paper_meta": _meta_from_chunks(compact_chunks),
        "chunks": compact_chunks,
        "required_fields": list(REQUIRED_NOTE_FIELDS),
        "score_dimensions": list(SCORE_DIMENSIONS),
        "not_disclosed_text": "输入未披露",
        "forbidden_outputs": ["alpha_signal", "factor", "factor_expression", "python_code"],
    }
    raw_note = run_json_prompt(
        client,
        system_prompt=system_prompt,
        user_payload=json.dumps(payload, ensure_ascii=False),
        task_name="paper_reading_note_v1",
    )
    return _normalize_note(raw_note, compact_chunks)


__all__ = ["build_chunk_reading_note", "build_llm_reading_note", "merge_chunk_reading_notes", "select_reading_chunks"]