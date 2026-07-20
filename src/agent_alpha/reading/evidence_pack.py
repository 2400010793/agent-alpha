from __future__ import annotations

import re
from collections import Counter
from typing import Any


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any, limit: int = 1400) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _entry(chunk: dict[str, Any], evidence_type: str, *, text: str | None = None, text_limit: int = 1400) -> dict[str, Any]:
    return {
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "section": str(chunk.get("section") or ""),
        "page": chunk.get("page"),
        "source_format": str(chunk.get("source_format") or ""),
        "evidence_type": evidence_type,
        "text": _clean_text(chunk.get("text") if text is None else text, text_limit),
    }


def _haystack(chunk: dict[str, Any]) -> str:
    values = [chunk.get("section", ""), chunk.get("text", "")]
    values.extend(_as_list(chunk.get("formula_blocks")))
    values.extend(_as_list(chunk.get("table_captions")))
    values.extend(_as_list(chunk.get("figure_captions")))
    return "\n".join(str(value) for value in values).casefold()


def _matches(chunk: dict[str, Any], *patterns: str) -> bool:
    text = _haystack(chunk)
    return any(re.search(pattern, text, flags=re.I) for pattern in patterns)


def _first_matching(chunks: list[dict[str, Any]], evidence_type: str, patterns: tuple[str, ...], *, limit: int, text_limit: int = 1400) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "")
        if chunk_id in seen:
            continue
        if _matches(chunk, *patterns):
            out.append(_entry(chunk, evidence_type, text_limit=text_limit))
            seen.add(chunk_id)
        if len(out) >= limit:
            break
    return out


def _formula_evidence(chunks: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        formulas = _as_list(chunk.get("formula_blocks"))
        if formulas:
            out.append({**_entry(chunk, "formula_evidence"), "formula_blocks": [_clean_text(item, 500) for item in formulas[:5]]})
        elif _matches(chunk, r"\bequation\b", r"\bformula\b", r"\bwhere\b", r"\bdefine\b", r"公式", r"变量"):
            out.append(_entry(chunk, "formula_evidence"))
        if len(out) >= limit:
            break
    return out


def _variable_definitions(chunks: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    return _first_matching(
        chunks,
        "variable_definition",
        (r"\bwhere\b", r"\bdefine[sd]?\b", r"\bvariable\b", r"\bdenote[sd]?\b", r"变量", r"定义"),
        limit=limit,
    )


def _section_map(chunks: list[dict[str, Any]], limit: int = 80) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        section = str(chunk.get("section") or "").strip() or "document"
        if section.casefold() in seen:
            continue
        seen.add(section.casefold())
        out.append({"section": section, "first_chunk_id": str(chunk.get("chunk_id") or ""), "source_format": str(chunk.get("source_format") or "")})
        if len(out) >= limit:
            break
    return out


def _quality(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    sections = Counter(str(chunk.get("section") or "document") for chunk in chunks)
    formula_count = sum(len(_as_list(chunk.get("formula_blocks"))) for chunk in chunks)
    return {
        "chunk_count": len(chunks),
        "section_count": len(sections),
        "formula_block_count": formula_count,
        "source_formats": sorted({str(chunk.get("source_format") or "") for chunk in chunks if chunk.get("source_format")}),
    }


def _missing_evidence(pack: dict[str, Any]) -> dict[str, str]:
    checks = {
        "formula": "formula_evidence",
        "variables": "variable_definitions",
        "method": "method_evidence",
        "data_sample": "data_sample_evidence",
        "empirical_results": "empirical_results",
        "experimental_code": "code_evidence",
        "conclusion_limits": "conclusion_evidence",
    }
    return {key: "输入未披露" for key, field in checks.items() if not pack.get(field)}


def build_evidence_pack_v2(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a new2-style evidence pack from parsed document chunks.

    This layer is intentionally before LLM reading: PDFs, LaTeX source packages,
    HTML, and Markdown are parsed into chunks first; the LLM reads this evidence
    pack rather than raw source files.
    """
    chunk_dicts = [dict(chunk) for chunk in chunks]
    pack: dict[str, Any] = {
        "quality": _quality(chunk_dicts),
        "section_map": _section_map(chunk_dicts),
        "intro_claims": _first_matching(chunk_dicts, "intro_claim", (r"\babstract\b", r"\bintroduction\b", r"\bmotivation\b", r"\bcontribution\b", r"\bproblem\b"), limit=8),
        "formula_evidence": _formula_evidence(chunk_dicts),
        "variable_definitions": _variable_definitions(chunk_dicts),
        "method_evidence": _first_matching(chunk_dicts, "method_evidence", (r"\bmethod\b", r"\bmodel\b", r"\bapproach\b", r"\bprocedure\b", r"\bestimat"), limit=6),
        "data_sample_evidence": _first_matching(chunk_dicts, "data_sample_evidence", (r"\bdata\b", r"\bsample\b", r"\bdataset\b", r"\bmarket\b", r"\bstock\b", r"\btrade\b", r"\bquote\b"), limit=6),
        "empirical_results": _first_matching(chunk_dicts, "empirical_result", (r"\bempirical\b", r"\bresult\b", r"\btable\b", r"\bfigure\b", r"\bregression\b", r"\bperformance\b", r"\bexperiment"), limit=6),
        "experimental_formula_evidence": _first_matching(chunk_dicts, "experimental_formula_evidence", (r"\bexperiment\b", r"\bsimulation\b", r"\bmetric\b", r"\btest\b"), limit=6),
        "code_evidence": _first_matching(chunk_dicts, "code_evidence", (r"\balgorithm\b", r"\bcode\b", r"\bpseudocode\b", r"\bimplementation\b"), limit=4),
        "conclusion_evidence": _first_matching(chunk_dicts, "conclusion_evidence", (r"\bconclusion\b", r"\bdiscussion\b", r"\blimitation\b", r"\bfuture\b", r"\bcaveat\b", r"\bcost\b", r"\bcapacity\b"), limit=6),
        "excluded_sections": [],
    }
    pack["missing_evidence"] = _missing_evidence(pack)
    return pack


def build_reading_tasks_from_evidence_pack(evidence_pack_v2: dict[str, Any], paper_meta: dict[str, Any]) -> list[dict[str, Any]]:
    source_anchor = {"source_kind": "document_chunks", "paper_id": paper_meta.get("paper_id", "")}
    return [
        {
            "chunk_id": "overview_claims",
            "task": "Read the paper frame: problem, central claim, contribution, mechanism outline, section map, and intro claims.",
            "article_meta": paper_meta,
            "evidence": {
                "quality": evidence_pack_v2.get("quality"),
                "section_map": evidence_pack_v2.get("section_map"),
                "intro_claims": evidence_pack_v2.get("intro_claims"),
                "source_anchor": source_anchor,
            },
        },
        {
            "chunk_id": "formula_variables",
            "task": "Extract formulas, variable meanings, observability, and how formulas connect to the mechanism. Do not infer empirical performance.",
            "article_meta": paper_meta,
            "evidence": {
                "formula_evidence": evidence_pack_v2.get("formula_evidence"),
                "variable_definitions": evidence_pack_v2.get("variable_definitions"),
                "source_anchor": source_anchor,
            },
        },
        {
            "chunk_id": "method_data_results",
            "task": "Extract method logic, data/sample setup, empirical design, and disclosed results. Mark anything not disclosed explicitly.",
            "article_meta": paper_meta,
            "evidence": {
                "method_evidence": evidence_pack_v2.get("method_evidence"),
                "data_sample_evidence": evidence_pack_v2.get("data_sample_evidence"),
                "empirical_results": evidence_pack_v2.get("empirical_results"),
                "source_anchor": source_anchor,
            },
        },
        {
            "chunk_id": "experimental_code",
            "task": "Read experimental formulas and algorithm/code snippets. Extract what the experiment/code computes and implementation constraints.",
            "article_meta": paper_meta,
            "evidence": {
                "experimental_formula_evidence": evidence_pack_v2.get("experimental_formula_evidence"),
                "code_evidence": evidence_pack_v2.get("code_evidence"),
                "source_anchor": source_anchor,
            },
        },
        {
            "chunk_id": "conclusion_limits",
            "task": "Read conclusion/discussion/limitations evidence. Extract final claims, caveats, future-work boundaries, and constraints.",
            "article_meta": paper_meta,
            "evidence": {
                "conclusion_evidence": evidence_pack_v2.get("conclusion_evidence"),
                "quality": evidence_pack_v2.get("quality"),
                "missing_evidence": evidence_pack_v2.get("missing_evidence"),
                "excluded_sections": evidence_pack_v2.get("excluded_sections"),
                "source_anchor": source_anchor,
            },
        },
    ]


__all__ = ["build_evidence_pack_v2", "build_reading_tasks_from_evidence_pack"]