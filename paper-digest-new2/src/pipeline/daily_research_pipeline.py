#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import gzip
import hashlib
import html
import io
import json
import math
import multiprocessing as mp
import queue
import os
import re
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import yaml

try:
    from src.factor.evaluation.quality_rules import DEFAULT_THRESHOLDS_PATH, paper_hf_proxy_quality_label
except ImportError:  # pragma: no cover - keeps import robust when packaged differently
    try:
        from src.factor.evaluation.quality_rules import DEFAULT_THRESHOLDS_PATH, paper_hf_proxy_quality_label
    except ImportError:  # pragma: no cover - final fallback for unusual packaging
        DEFAULT_THRESHOLDS_PATH = Path(__file__).resolve().parents[2] / "config" / "factor_quality_thresholds.yaml"

        def paper_hf_proxy_quality_label(metrics: Dict[str, object], tier: str = "small", path: Path = DEFAULT_THRESHOLDS_PATH) -> Dict[str, str]:
            del metrics, path
            return {"label": f"weak({tier})", "class": "quality-weak", "reason": "quality rules unavailable"}

_LAST_LLM_REQUEST_TS = 0.0
SCORE_DIMENSIONS = (
    ("relevance", "相关性"),
    ("mechanism", "机制可信度"),
    ("statistical", "统计可信度"),
    ("implementation", "可实现性"),
    ("cost_sensitivity", "成本敏感性"),
    ("generality", "普适性"),
)
LLM_ANALYSIS_SCHEMA = "schema-v6"
_HF_FAITHFULNESS_RENDER_CACHE: Optional[Tuple[Dict[Tuple[str, str], Dict[str, object]], Dict[Tuple[str, str], Dict[str, object]]]] = None
ALLOWED_FACTOR_FIELDS = {
    "code",
    "date",
    "delay_time",
    "processing_time",
    "close",
    "volume",
    "money",
    "totalDeputeBuy",
    "totalDeputeSell",
    "averageBuy",
    "averageSell",
    "last_close",
    *(f"askP{i}" for i in range(1, 11)),
    *(f"bidP{i}" for i in range(1, 11)),
    *(f"askV{i}" for i in range(1, 11)),
    *(f"bidV{i}" for i in range(1, 11)),
}
ALLOWED_HORIZONS = {"ret10s", "ret30s", "ret60s", "ret120s"}
ALLOWED_FACTOR_TEMPLATES = {
    "order_book_imbalance",
    "bid_ask_spread",
    "depth_pressure",
    "weighted_mid_price_deviation",
    "trade_intensity",
    "money_flow",
    "short_return_momentum",
    "short_return_reversal",
    "volume_pressure",
    "unsupported",
}
ALLOWED_DIRECTIONS = {"positive", "negative", "unknown"}
ALLOWED_FACTOR_STATUSES = {"candidate", "unsupported_fields"}
PROXY_STRENGTHS = {"direct", "derived", "weak_proxy", "unsupported", "future_pipeline"}
GENERATION_PROXY_STRENGTHS = {"direct", "derived"}
PAPER_HF_FACTOR_LIMIT = max(1, int(os.environ.get("PAPER_HF_FACTOR_LIMIT", "6")))
FACTOR_CANDIDATE_LIMIT = max(1, int(os.environ.get("PAPER_FACTOR_CANDIDATE_LIMIT", "6")))
ARXIV_EVIDENCE_ENABLED = os.environ.get("PAPER_ARXIV_EVIDENCE_ENABLED", "1") == "1"
ARXIV_EVIDENCE_TIMEOUT_SEC = max(1, int(os.environ.get("PAPER_ARXIV_EVIDENCE_TIMEOUT_SEC", "20")))
ARXIV_EVIDENCE_FORMULA_SNIPPETS = max(0, int(os.environ.get("PAPER_ARXIV_EVIDENCE_FORMULA_SNIPPETS", "8")))
ARXIV_EVIDENCE_SNIPPET_CHARS = max(200, int(os.environ.get("PAPER_ARXIV_EVIDENCE_SNIPPET_CHARS", "700")))
ARXIV_EVIDENCE_MAX_SOURCE_BYTES = max(100_000, int(os.environ.get("PAPER_ARXIV_EVIDENCE_MAX_SOURCE_BYTES", "5000000")))
ARXIV_EVIDENCE_INTRO_CHARS = max(500, int(os.environ.get("PAPER_ARXIV_EVIDENCE_INTRO_CHARS", "3000")))
ARXIV_EVIDENCE_OVERVIEW_SECTIONS = max(0, int(os.environ.get("PAPER_ARXIV_EVIDENCE_OVERVIEW_SECTIONS", "12")))
ARXIV_EVIDENCE_EMPIRICAL_SNIPPETS = max(0, int(os.environ.get("PAPER_ARXIV_EVIDENCE_EMPIRICAL_SNIPPETS", "6")))
ARXIV_EVIDENCE_METHOD_CHARS = max(1000, int(os.environ.get("PAPER_ARXIV_EVIDENCE_METHOD_CHARS", "5000")))
ARXIV_EVIDENCE_FORMULA_CONTEXT_CHARS = max(2000, int(os.environ.get("PAPER_ARXIV_EVIDENCE_FORMULA_CONTEXT_CHARS", "20000")))
ARXIV_EVIDENCE_EMPIRICAL_CHARS = max(1000, int(os.environ.get("PAPER_ARXIV_EVIDENCE_EMPIRICAL_CHARS", "8000")))
ARXIV_EVIDENCE_CONCLUSION_CHARS = max(1000, int(os.environ.get("PAPER_ARXIV_EVIDENCE_CONCLUSION_CHARS", "6000")))
ARXIV_EVIDENCE_CODE_CHARS = max(1000, int(os.environ.get("PAPER_ARXIV_EVIDENCE_CODE_CHARS", "6000")))
MECHANISM_TAXONOMY_CONTEXT_LIMIT = max(1, int(os.environ.get("PAPER_MECHANISM_TAXONOMY_CONTEXT_LIMIT", "3")))
FUTURE_RETURN_RE = re.compile(r"\bret\d+s\b")
VOLUME_LEVEL_RE = re.compile(r"^(bidV|askV)(\d+)$")
PRICE_LEVEL_RE = re.compile(r"^(bidP|askP)(\d+)$")
EXPRESSION_FUNC_RE = re.compile(r"\b(rolling_mean|rolling_sum|rolling_std|rolling_min|rolling_max|rolling_median|rolling_skew|expanding_mean|expanding_min|expanding_max|cumsum|first|pct_change|zscore|abs|sign|log|sqrt|clip|diff|ema)\s*\(")
EXPRESSION_FIELD_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
ALLOWED_EXPRESSION_FUNCS = {
    "rolling_mean",
    "rolling_sum",
    "rolling_std",
    "rolling_min",
    "rolling_max",
    "rolling_median",
    "rolling_skew",
    "expanding_mean",
    "expanding_min",
    "expanding_max",
    "cumsum",
    "first",
    "pct_change",
    "zscore",
    "abs",
    "sign",
    "log",
    "sqrt",
    "clip",
    "diff",
    "ema",
}
DEFAULT_PROXY_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "proxy_registry.yaml"
DEFAULT_MECHANISM_TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "config" / "mechanism_taxonomy.yaml"
SITE_INDEX_URL = "http://10.9.22.11:7880/index.html"
_PROXY_REGISTRY_CACHE: Optional[Dict[str, object]] = None
_MECHANISM_TAXONOMY_CACHE: Optional[List[Dict[str, object]]] = None


from src.io.config import SourceConfig


def _to_utc_iso(dt: datetime) -> str:
    from src.io.datetime_utils import _to_utc_iso as _impl

    return _impl(dt)


def _parse_datetime_value(raw: Optional[str]) -> Optional[datetime]:
    from src.io.datetime_utils import _parse_datetime_value as _impl

    return _impl(raw)


def _parse_datetime(raw: Optional[str]) -> str:
    from src.io.datetime_utils import _parse_datetime as _impl

    return _impl(raw)


def _is_within_max_age(raw: Optional[str], *, now: datetime, max_age_days: int) -> bool:
    from src.io.datetime_utils import _is_within_max_age as _impl

    return _impl(raw, now=now, max_age_days=max_age_days)


def _row_is_within_max_age(row: Dict[str, object], *, now: datetime, max_age_days: int) -> bool:
    from src.io.datetime_utils import _row_is_within_max_age as _impl

    return _impl(row, now=now, max_age_days=max_age_days)


def _build_fetch_start_ts(now: datetime, max_age_days: int) -> str:
    from src.io.datetime_utils import _build_fetch_start_ts as _impl

    return _impl(now, max_age_days)


def _build_fetch_end_ts(now: datetime) -> str:
    from src.io.datetime_utils import _build_fetch_end_ts as _impl

    return _impl(now)


def _build_arxiv_query_window(fetch_month: str, now: datetime, max_age_days: int) -> Tuple[str, str]:
    from src.io.datetime_utils import _build_arxiv_query_window as _impl

    return _impl(fetch_month, now, max_age_days)


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _extract_arxiv_id(url: str) -> str:
    from src.arxiv.ids import _extract_arxiv_id as _impl

    return _impl(url)


def _extract_doi(text: str) -> str:
    from src.arxiv.ids import _extract_doi as _impl

    return _impl(text)


def _extract_ssrn_id(url: str) -> str:
    from src.arxiv.ids import _extract_ssrn_id as _impl

    return _impl(url)


def _strip_tex_preamble(text: str) -> str:
    match = re.search(r"\\begin\{document\}", text, flags=re.I)
    return text[match.end() :] if match else text


def _tex_unescape(text: str) -> str:
    return text.replace(r"\_", "_").replace(r"\&", "&").replace("&amp;", "&")


def pre_clean_tex(tex_content: str) -> str:
    tex_content = re.sub(r"(?<!\\)%.*$", "", tex_content, flags=re.MULTILINE)
    tex_content = _strip_tex_preamble(tex_content)
    tex_content = re.sub(r"\\begin\{(tikzpicture|pgfplots|image|figure)\}.*?\\end\{\1\}", "", tex_content, flags=re.S | re.I)
    tex_content = re.sub(r"\\begin\{(tabular|table|matrix|longtable|sidewaystable)\}.*?\\end\{\1\}", "[Table/Matrix Data Omitted]", tex_content, flags=re.S | re.I)
    tex_content = re.sub(r"\n\s*\n+", "\n\n", tex_content)
    return _tex_unescape(tex_content)


def _strip_tex_commands(text: str) -> str:
    text = re.sub(r"(?<!\\)%.*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"\\(?:cite|ref|label|url|href|emph|textbf|textit|mathbf|mathrm|footnote)(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\(?:textit|textbf|underline)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", text)
    text = re.sub(r"[{}]", " ", text)
    return _normalize_text(_tex_unescape(text))


def _clip_snippet(text: str, max_chars: int = ARXIV_EVIDENCE_SNIPPET_CHARS) -> str:
    text = _normalize_text(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _tex_sections(text: str) -> List[Dict[str, object]]:
    text = pre_clean_tex(text)
    matches = list(re.finditer(r"\\(?:section|subsection|subsubsection)\*?\{([^{}]{1,160})\}", text))
    sections: List[Dict[str, object]] = []
    for idx, match in enumerate(matches):
        heading = _strip_tex_commands(match.group(1))[:160]
        if not heading:
            continue
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections.append({"heading": heading, "start": start, "end": end, "raw": text[start:end]})
    return sections


def _is_tail_section(heading: str) -> bool:
    return bool(re.search(r"conclusion|discussion|future work|references|bibliography|acknowledg|appendix", heading, flags=re.I))


def _extract_tex_section_overview(text: str, limit: int = ARXIV_EVIDENCE_OVERVIEW_SECTIONS) -> str:
    lines: List[str] = []
    clean = pre_clean_tex(text)
    matches = re.findall(r"\\(section|subsection|subsubsection)\*?\{([^{}]+)\}", clean)
    for sec_type, sec_title in matches:
        heading = _strip_tex_commands(sec_title)[:160]
        if not heading or _is_tail_section(heading):
            continue
        indent = "" if sec_type == "section" else "  " if sec_type == "subsection" else "    "
        lines.append(f"{indent}- {heading}")
        if len(lines) >= limit:
            break
    return "\n".join(lines) if lines else "Section overview undetected."


def _extract_tex_method_blocks(text: str) -> List[Dict[str, str]]:
    wanted = re.compile(r"method|methodology|model|factor construction|construction|empirical results|empirical|setup|data", flags=re.I)
    blocks: List[Dict[str, str]] = []
    for section in _tex_sections(text):
        heading = str(section.get("heading") or "")
        if _is_tail_section(heading) or not wanted.search(heading):
            continue
        clean = _strip_tex_commands(str(section.get("raw") or ""))
        if clean:
            blocks.append({"section": heading, "text": _clip_snippet(clean, ARXIV_EVIDENCE_METHOD_CHARS)})
    return blocks[:4]


def _extract_tex_intro_context(text: str) -> str:
    body = pre_clean_tex(text)
    for section in _tex_sections(body):
        heading = str(section.get("heading") or "")
        if re.search(r"introduction|background|overview|intro", heading, flags=re.I):
            return _clip_snippet(_strip_tex_commands(str(section.get("raw") or "")), ARXIV_EVIDENCE_INTRO_CHARS)
    abstract_match = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", body, flags=re.S | re.I)
    if abstract_match:
        after_abstract = body[abstract_match.end() :]
        next_section = re.search(r"\\(?:section|subsection)\*?\{", after_abstract)
        introish = after_abstract[: next_section.start()] if next_section else after_abstract[:5000]
        introish = _strip_tex_commands(introish)
        if introish:
            return _clip_snippet(introish, ARXIV_EVIDENCE_INTRO_CHARS)
    return _clip_snippet(_strip_tex_commands(body[:5000]), ARXIV_EVIDENCE_INTRO_CHARS)


def _extract_tex_formula_contexts(text: str, max_chars: int = ARXIV_EVIDENCE_FORMULA_CONTEXT_CHARS) -> str:
    lines = pre_clean_tex(text).split("\n")
    snippets: List[str] = []
    starts = (r"\begin{equation", r"\begin{align", r"\begin{gather", "$$")
    i = 0
    while i < len(lines):
        line = lines[i]
        if any(marker in line for marker in starts):
            start_line = max(0, i - 3)
            end_idx = i
            while end_idx < len(lines):
                end_line_text = lines[end_idx]
                if end_idx != i and "$$" in end_line_text:
                    break
                if any(marker.replace("begin", "end") in end_line_text for marker in starts if marker != "$$"):
                    break
                end_idx += 1
            end_line = min(len(lines), end_idx + 9)
            snippets.append("\n".join(lines[start_line:end_line]))
            i = end_line
        else:
            i += 1
        if sum(len(snippet) for snippet in snippets) >= max_chars:
            break
    return _tex_unescape("\n\n---\n\n".join(snippets))[:max_chars]


def _extract_tex_empirical_setup_snippets(text: str, limit: int = ARXIV_EVIDENCE_EMPIRICAL_SNIPPETS) -> List[Dict[str, str]]:
    time_keywords = re.compile(r"window|frequency|lag|rolling|daily|minutely|monthly|lookback|horizon", flags=re.I)
    setup_keywords = re.compile(r"estimation|sample|data|test|backtest|portfolio|parameter|rebalance|transaction cost|liquidity", flags=re.I)
    snippets: List[Dict[str, str]] = []
    for section in _tex_sections(pre_clean_tex(text)):
        heading = str(section.get("heading") or "")
        if _is_tail_section(heading):
            continue
        raw = str(section.get("raw") or "")
        paragraphs = [part for part in re.split(r"\n\s*\n+", raw) if time_keywords.search(part) and setup_keywords.search(part)]
        for paragraph in paragraphs[:2]:
            clean = _strip_tex_commands(paragraph)
            if clean:
                snippets.append({"section": heading or "empirical_setup", "text": _clip_snippet(clean)})
            if len(snippets) >= limit:
                return snippets
    return snippets[:limit]


def _extract_tex_section_snippets(text: str, wanted: re.Pattern[str], *, max_chars: int, limit: int = 4, include_tail: bool = False) -> List[Dict[str, str]]:
    snippets: List[Dict[str, str]] = []
    for section in _tex_sections(pre_clean_tex(text)):
        heading = str(section.get("heading") or "")
        if not heading or not wanted.search(heading):
            continue
        if _is_tail_section(heading) and not include_tail and not re.search(r"conclusion|discussion|future work|limitations?", heading, flags=re.I):
            continue
        clean = _strip_tex_commands(str(section.get("raw") or ""))
        if clean:
            snippets.append({"section": heading, "text": _clip_snippet(clean, max_chars)})
        if len(snippets) >= limit:
            break
    return snippets


def _extract_tex_conclusion_context(text: str) -> List[Dict[str, str]]:
    wanted = re.compile(r"conclusion|discussion|future work|limitations?", flags=re.I)
    return _extract_tex_section_snippets(text, wanted, max_chars=ARXIV_EVIDENCE_CONCLUSION_CHARS, limit=4, include_tail=True)


def _extract_tex_code_or_algorithm_snippets(text: str, limit: int = 6) -> List[Dict[str, str]]:
    clean = pre_clean_tex(text)
    snippets: List[Dict[str, str]] = []
    wanted_sections = re.compile(r"algorithm|implementation|pseudo[- ]?code|procedure|computation|estimation algorithm|simulation", flags=re.I)
    for item in _extract_tex_section_snippets(clean, wanted_sections, max_chars=ARXIV_EVIDENCE_CODE_CHARS, limit=limit, include_tail=True):
        snippets.append({**item, "evidence_type": "code_or_algorithm_section"})
        if len(snippets) >= limit:
            return snippets
    env_re = re.compile(r"\\begin\{(algorithm|algorithmic|lstlisting|verbatim|minted)\}(.*?)\\end\{\1\}", flags=re.S | re.I)
    for match in env_re.finditer(clean):
        raw = match.group(0)
        text_value = _strip_tex_commands(raw)
        if text_value:
            snippets.append({"section": match.group(1), "text": _clip_snippet(text_value, ARXIV_EVIDENCE_CODE_CHARS), "evidence_type": "code_or_algorithm_environment"})
        if len(snippets) >= limit:
            break
    return snippets[:limit]


def _extract_tex_experimental_formula_contexts(text: str, max_chars: int = 8000) -> str:
    wanted = re.compile(r"experiment|empirical|result|data|model comparison|evaluation|backtest|simulation", flags=re.I)
    snippets: List[str] = []
    for section in _tex_sections(pre_clean_tex(text)):
        heading = str(section.get("heading") or "")
        if not heading or _is_tail_section(heading) or not wanted.search(heading):
            continue
        context = _extract_tex_formula_contexts(str(section.get("raw") or ""), max_chars=max_chars)
        if context:
            snippets.append(f"SECTION: {heading}\n{context}")
        if sum(len(snippet) for snippet in snippets) >= max_chars:
            break
    return _tex_unescape("\n\n---\n\n".join(snippets))[:max_chars]


def _extract_tex_include_audit(text: str) -> Dict[str, object]:
    clean = pre_clean_tex(text)
    refs = re.findall(r"\\(?:input|include)\{([^{}]+)\}", clean)
    return {
        "input_include_count": len(refs),
        "input_include_examples": refs[:20],
        "has_many_input_includes": len(refs) >= 5,
    }


def _tex_noise_residual_audit(text: str) -> Dict[str, int]:
    clean = pre_clean_tex(text)
    return {
        "figure_like_blocks_remaining": len(re.findall(r"\\begin\{(?:tikzpicture|pgfplots|image|figure)\}", clean, flags=re.I)),
        "table_like_blocks_remaining": len(re.findall(r"\\begin\{(?:tabular|table|matrix|longtable|sidewaystable)\}", clean, flags=re.I)),
    }


def _evidence_quality_checks(evidence: Dict[str, object]) -> Dict[str, object]:
    formula_contexts = str(evidence.get("formula_contexts") or "")
    section_overview = str(evidence.get("section_overview") or "")
    intro_context = str(evidence.get("intro_context") or "")
    conclusion_context = evidence.get("conclusion_context") if isinstance(evidence.get("conclusion_context"), list) else []
    code_snippets = evidence.get("code_or_algorithm_snippets") if isinstance(evidence.get("code_or_algorithm_snippets"), list) else []
    residual_audit = evidence.get("table_figure_residual_audit") if isinstance(evidence.get("table_figure_residual_audit"), dict) else {}
    figure_residue = int(residual_audit.get("figure_like_blocks_remaining") or 0)
    table_residue = int(residual_audit.get("table_like_blocks_remaining") or 0)
    section_lines = [line for line in section_overview.splitlines() if line.strip() and "undetected" not in line.lower()]
    formula_has_math = bool(re.search(r"\$|\\begin\{", formula_contexts))
    checks = {
        "formula_contexts_len": len(formula_contexts),
        "formula_has_tex_math_markers": formula_has_math,
        "section_overview_line_count": len(section_lines),
        "intro_context_len": len(intro_context),
        "conclusion_context_count": len(conclusion_context),
        "code_or_algorithm_snippet_count": len(code_snippets),
        "figure_like_blocks_remaining": figure_residue,
        "table_like_blocks_remaining": table_residue,
        "is_trusted": True,
        "reasons": [],
    }
    reasons: List[str] = []
    if formula_contexts and not formula_has_math:
        reasons.append("formula_contexts_nonempty_without_tex_math_markers")
    if len(section_lines) <= 2:
        reasons.append("section_overview_too_short_possible_input_include_or_nonstandard_tex")
    if len(intro_context) < 200:
        reasons.append("intro_context_too_short")
    if not formula_contexts:
        reasons.append("formula_contexts_empty")
    if figure_residue:
        reasons.append("figure_like_blocks_remaining_after_clean")
    if table_residue:
        reasons.append("table_like_blocks_remaining_after_clean")
    checks["reasons"] = reasons
    checks["is_trusted"] = not reasons
    return checks


def _normalize_tex_ref(ref: str) -> str:
    ref = ref.strip().lstrip("./")
    return ref if ref.lower().endswith(".tex") else f"{ref}.tex"


def _select_main_tex_source(source_texts: List[Tuple[str, str]]) -> Tuple[str, str]:
    candidates = [(name, text) for name, text in source_texts if not _is_likely_non_article_source(name, text)]
    candidates = candidates or source_texts

    def score(item: Tuple[str, str]) -> Tuple[int, int]:
        name, text = item
        lowered_name = name.lower()
        lowered_text = text[:20000].lower()
        value = 0
        value += 20 if re.search(r"\\begin\{document\}", text) else 0
        value += 12 if re.search(r"\\documentclass", text) else 0
        value += 10 if re.search(r"\\begin\{abstract\}", text, flags=re.I) else 0
        value += 5 * len(re.findall(r"\\section\*?\{", text[:50000]))
        value += 8 if re.search(r"\\section\*?\{[^{}]*(introduction|background)", text, flags=re.I) else 0
        value += 6 if re.search(r"\\section\*?\{[^{}]*(conclusion|discussion)", text, flags=re.I) else 0
        value += 4 if re.search(r"\\(?:input|include)\{", text) else 0
        if re.search(r"(^|/)(supplement|appendix|references?|bibliography|rqufguide|guide|template|sample)", lowered_name):
            value -= 40
        if re.search(r"latex guide for authors|document preparation system|class file|taylor & francis|rquf2e\.cls", lowered_text):
            value -= 80
        return value, len(text)

    return max(candidates, key=score) if candidates else ("", "")


def _is_likely_non_article_source(name: str, text: str) -> bool:
    lowered_name = name.lower().lstrip("./")
    lowered_text = text[:20000].lower()
    if lowered_name.endswith(('.bbl', '.bst', '.cls', '.sty')):
        return True
    if re.search(r"(^|/)(rqufguide|guide|template|sample|readme|instructions?)\.(tex|ltx|txt|gz)$", lowered_name):
        return True
    if re.search(r"latex guide for authors|document preparation system|class file|taylor & francis|rquf2e\.cls", lowered_text):
        return True
    return False


def _assemble_arxiv_tex_corpus(source_texts: List[Tuple[str, str]], max_files: int = 16) -> Tuple[str, List[str], str]:
    if not source_texts:
        return "", [], ""
    article_source_texts = [(name, text) for name, text in source_texts if not _is_likely_non_article_source(name, text)] or source_texts
    source_map = {name.lstrip("./"): text for name, text in article_source_texts}
    main_name, main_text = _select_main_tex_source(article_source_texts)
    ordered_names = [main_name] if main_name else []
    for ref in re.findall(r"\\(?:input|include)\{([^{}]+)\}", main_text):
        wanted = _normalize_tex_ref(ref)
        candidates = [wanted, wanted.lstrip("./")]
        candidates.extend(name for name in source_map if name.endswith("/" + wanted) or name.endswith(wanted))
        for candidate in candidates:
            if candidate in source_map and candidate not in ordered_names:
                ordered_names.append(candidate)
                break
        if len(ordered_names) >= max_files:
            break
    if len(ordered_names) < min(max_files, len(source_texts)):
        for name, _ in sorted(article_source_texts, key=lambda item: (0 if item[0] == main_name else 1, -len(item[1]))):
            if name not in ordered_names:
                ordered_names.append(name)
            if len(ordered_names) >= max_files:
                break
    combined = "\n\n".join(pre_clean_tex(source_map.get(name, "")) for name in ordered_names)
    return combined, ordered_names, main_name


def _decode_arxiv_source_file(name: str, payload: bytes) -> str:
    if name.endswith(".gz"):
        try:
            payload = gzip.decompress(payload)
        except OSError:
            return ""
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def _extract_arxiv_source_texts(payload: bytes) -> Tuple[List[Tuple[str, str]], str]:
    fileobj = io.BytesIO(payload)
    try:
        texts: List[Tuple[str, str]] = []
        with tarfile.open(fileobj=fileobj, mode="r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile() or member.size > ARXIV_EVIDENCE_MAX_SOURCE_BYTES:
                    continue
                if not member.name.lower().endswith((".tex", ".ltx", ".bbl", ".txt", ".tex.gz")):
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                text = _decode_arxiv_source_file(member.name, extracted.read(ARXIV_EVIDENCE_MAX_SOURCE_BYTES))
                if text.strip():
                    texts.append((member.name, text))
        return texts, "e-print-tar"
    except tarfile.TarError:
        pass
    try:
        return [("source.tex", gzip.decompress(payload).decode("utf-8", errors="replace"))], "e-print-gzip"
    except OSError:
        return [("source.tex", payload[:ARXIV_EVIDENCE_MAX_SOURCE_BYTES].decode("utf-8", errors="replace"))], "e-print-raw"


def build_arxiv_evidence_pack(row: Dict[str, object], *, timeout_sec: int = ARXIV_EVIDENCE_TIMEOUT_SEC, user_agent: str = "factor-study-paper-bot/1.0") -> Dict[str, object]:
    if not ARXIV_EVIDENCE_ENABLED:
        return {}
    url = str(row.get("url") or "")
    arxiv_id = _extract_arxiv_id(url)
    if not arxiv_id:
        return {}
    evidence: Dict[str, object] = {"source": "arxiv", "arxiv_id": arxiv_id, "url": url, "status": "unavailable"}
    try:
        source_url = f"https://export.arxiv.org/e-print/{urllib.parse.quote(arxiv_id)}"
        payload: Optional[bytes] = None
        fetch_errors: List[str] = []
        for use_proxy in (True, False):
            try:
                payload = fetch_url(source_url, timeout_sec=timeout_sec, user_agent=user_agent, use_proxy=use_proxy)
                break
            except Exception as exc:
                error_summary = _summarize_llm_error(exc)
                fetch_errors.append(f"{'proxy' if use_proxy else 'direct'}:{error_summary}")
                if "HTTP Error 429" in error_summary:
                    break
        if payload is None:
            raise RuntimeError("; ".join(fetch_errors))
        if len(payload) > ARXIV_EVIDENCE_MAX_SOURCE_BYTES * 3:
            payload = payload[: ARXIV_EVIDENCE_MAX_SOURCE_BYTES * 3]
        source_texts, source_kind = _extract_arxiv_source_texts(payload)
        combined, ordered_source_files, main_source_file = _assemble_arxiv_tex_corpus(source_texts)
        formula_contexts = _extract_tex_formula_contexts(combined)
        experimental_formula_contexts = _extract_tex_experimental_formula_contexts(combined)
        section_overview = _extract_tex_section_overview(combined)
        intro_context = _extract_tex_intro_context(combined)
        empirical_setup_snippets = _extract_tex_empirical_setup_snippets(combined)
        conclusion_context = _extract_tex_conclusion_context(combined)
        code_or_algorithm_snippets = _extract_tex_code_or_algorithm_snippets(combined)
        evidence.update(
            {
                "status": "ok" if combined.strip() else "empty_source",
                "source_kind": source_kind,
            "main_source_file": main_source_file,
            "source_files": ordered_source_files[:16],
                "section_overview": section_overview,
                "intro_context": intro_context,
                "formula_contexts": formula_contexts,
                "experimental_formula_contexts": experimental_formula_contexts,
                "method_blocks": _extract_tex_method_blocks(combined),
                "empirical_setup_snippets": empirical_setup_snippets,
                "conclusion_context": conclusion_context,
                "code_or_algorithm_snippets": code_or_algorithm_snippets,
                "input_include_audit": _extract_tex_include_audit(combined),
                "table_figure_residual_audit": _tex_noise_residual_audit(combined),
                "excluded_sections": "references/appendix",
            }
        )
        evidence["quality_checks"] = _evidence_quality_checks(evidence)
        if not bool(evidence["quality_checks"].get("is_trusted")):
            evidence["status"] = "RAW_TEX_EXTRACTION_FAILED_FALLBACK_TO_ABSTRACT"
            evidence["fallback_abstract"] = str(row.get("summary") or "")[:3000]
    except Exception as exc:
        evidence["status"] = "fetch_failed"
        evidence["error"] = _summarize_llm_error(exc)
    return evidence


def _canonicalize_url(url: str) -> str:
    from src.io.identity import _canonicalize_url as _impl

    return _impl(url)


def _canonicalize_title(title: str) -> str:
    from src.io.identity import _canonicalize_title as _impl

    return _impl(title)


def _entry_key(url: str, title: str, source_id: str) -> str:
    from src.io.identity import _entry_key as _impl

    return _impl(url, title, source_id)


def _entry_identity_bases(url: str, title: str) -> List[str]:
    from src.io.identity import _entry_identity_bases as _impl

    return _impl(url, title)


def _entry_identity_keys(url: str, title: str) -> List[str]:
    from src.io.identity import _entry_identity_keys as _impl

    return _impl(url, title)


def _row_entry_key(row: Dict[str, object]) -> str:
    from src.io.identity import _row_entry_key as _impl

    return _impl(row)


def _row_identity_keys(row: Dict[str, object]) -> List[str]:
    from src.io.identity import _row_identity_keys as _impl

    return _impl(row)


def load_config(config_path: Path) -> Tuple[Dict[str, object], List[SourceConfig]]:
    from src.io.config import load_config as _load_config

    return _load_config(config_path)


def fetch_url(url: str, timeout_sec: int, user_agent: str, *, use_proxy: bool = True) -> bytes:
    from src.io.http import fetch_url as _impl

    return _impl(url, timeout_sec, user_agent, use_proxy=use_proxy)


def _build_month_window(fetch_month: str) -> Tuple[str, str]:
    from src.io.datetime_utils import _build_month_window as _impl

    return _impl(fetch_month)


def fetch_entries_for_source(
    src: SourceConfig,
    *,
    timeout_sec: int,
    user_agent: str,
    max_items: int,
    fetch_month: str,
    fetch_now: datetime,
    max_age_days: int,
) -> List[Dict[str, str]]:
    from src.io.http import fetch_entries_for_source as _impl

    return _impl(src, timeout_sec=timeout_sec, user_agent=user_agent, max_items=max_items, fetch_month=fetch_month, fetch_now=fetch_now, max_age_days=max_age_days)


def _raise_source_timeout(signum: int, frame: object) -> None:
    from src.io.http import _raise_source_timeout as _impl

    _impl(signum, frame)


def _fetch_entries_worker(
    result_queue: object,
    src: SourceConfig,
    timeout_sec: int,
    user_agent: str,
    max_items: int,
    fetch_month: str,
    fetch_now_iso: str,
    max_age_days: int,
) -> None:
    from src.io.http import _fetch_entries_worker as _impl

    _impl(result_queue, src, timeout_sec, user_agent, max_items, fetch_month, fetch_now_iso, max_age_days)


def fetch_entries_for_source_with_timeout(
    src: SourceConfig,
    *,
    timeout_sec: int,
    source_timeout_sec: int,
    user_agent: str,
    max_items: int,
    fetch_month: str,
    fetch_now: datetime,
    max_age_days: int,
) -> List[Dict[str, str]]:
    from src.io.http import fetch_entries_for_source_with_timeout as _impl

    return _impl(
        src,
        timeout_sec=timeout_sec,
        source_timeout_sec=source_timeout_sec,
        user_agent=user_agent,
        max_items=max_items,
        fetch_month=fetch_month,
        fetch_now=fetch_now,
        max_age_days=max_age_days,
    )


def _find_text(node: ET.Element, names: Iterable[str], ns: Optional[Dict[str, str]] = None) -> str:
    from src.io.feed import _find_text as _impl

    return _impl(node, names, ns)


def _html_attr(tag: str, attr: str) -> str:
    from src.io.feed import _html_attr as _impl

    return _impl(tag, attr)


def _html_meta_content(page_html: str, *names: str) -> str:
    from src.io.feed import _html_meta_content as _impl

    return _impl(page_html, *names)


def _html_title(page_html: str) -> str:
    from src.io.feed import _html_title as _impl

    return _impl(page_html)


def parse_sitemap_entries(
    xml_bytes: bytes,
    *,
    timeout_sec: int,
    user_agent: str,
    max_items: int,
    use_proxy: bool = True,
) -> List[Dict[str, str]]:
    from src.io.feed import parse_sitemap_entries as _impl

    return _impl(xml_bytes, timeout_sec=timeout_sec, user_agent=user_agent, max_items=max_items, use_proxy=use_proxy)


def parse_rss_or_atom(xml_bytes: bytes) -> List[Dict[str, str]]:
    from src.io.feed import parse_rss_or_atom as _impl

    return _impl(xml_bytes)


def keyword_match(text: str, keywords: List[str]) -> Tuple[bool, List[str]]:
    lowered = text.lower()
    hit = [kw for kw in keywords if kw.lower() in lowered]
    return (len(hit) > 0, hit)


def is_hf_factor_relevant(text: str, tags: List[str]) -> bool:
    lowered = text.lower()
    # Require at least one strong HFT/factor signal and one market context signal.
    # This avoids unrelated papers that happen to contain weak words like "alpha".
    strong_terms = (
        "high-frequency",
        "hft",
        "microstructure",
        "order book",
        "limit order book",
        "tick",
        "intraday",
        "market making",
        "transaction cost",
        "liquidity",
        "高频",
        "逐笔",
        "盘口",
        "订单簿",
        "委托",
        "做市",
        "微观结构",
        "因子",
        "alpha",
    )
    market_context_terms = (
        "trading",
        "trade",
        "market",
        "stock",
        "equity",
        "price",
        "return",
        "execution",
        "quote",
        "finance",
        "financial",
        "asset",
        "交易",
        "市场",
        "股票",
        "收益",
        "价格",
        "流动性",
        "成交",
    )
    tag_hit = " ".join(tags).lower()
    has_strong = any(t in lowered for t in strong_terms) or any(t in tag_hit for t in strong_terms)
    has_market_context = any(t in lowered for t in market_context_terms)
    return has_strong and has_market_context


def is_source_relevant(text: str, tags: List[str], source_type: str) -> bool:
    if is_hf_factor_relevant(text, tags):
        return True
    if source_type not in {"blog", "research_blog", "blog_mashup"}:
        return False
    lowered = text.lower()
    tag_hit = " ".join(tags).lower()
    blog_research_terms = (
        "factor",
        "factors",
        "factor investing",
        "factor analysis",
        "factor allocation",
        "anomaly",
        "anomalies",
        "alpha",
        "strategy",
        "strategies",
        "backtest",
        "backtesting",
        "replication",
        "portfolio",
        "asset allocation",
        "risk premia",
        "risk premium",
        "momentum",
        "time series",
        "time series momentum",
        "trend",
        "trend following",
        "mean reversion",
        "asset pricing",
        "cross-asset",
        "volatility",
        "statistical arbitrage",
        "pairs trading",
        "walk-forward",
        "out-of-sample",
        "machine learning",
        "ai agent",
        "prediction market",
        "因子",
        "策略",
        "组合",
        "回测",
        "资产配置",
    )
    market_context_terms = (
        "trading",
        "trade",
        "market",
        "stock",
        "equity",
        "asset",
        "portfolio",
        "return",
        "risk",
        "investment",
        "finance",
        "financial",
        "etf",
        "bitcoin",
        "crypto",
        "commodity",
        "commodities",
        "index",
        "indices",
        "cross-asset",
        "volatility",
        "bonds",
        "prediction market",
        "交易",
        "市场",
        "股票",
        "收益",
        "风险",
        "投资",
    )
    has_blog_research = any(term in lowered for term in blog_research_terms) or any(term in tag_hit for term in blog_research_terms)
    has_market_context = any(term in lowered for term in market_context_terms) or any(term in tag_hit for term in market_context_terms)
    return has_blog_research and has_market_context

def is_display_quality_row(row: Dict[str, object]) -> bool:
    source_type = str(row.get("source_type", "paper"))
    title = _normalize_text(str(row.get("title", "")))
    summary = _normalize_text(str(row.get("summary", "")))
    text = f"{title} {summary}"
    if not is_source_relevant(text, [str(x) for x in row.get("tags", [])], source_type):
        return False
    score = _metric_float(row.get("recommendation_score")) or 0.0
    pending = bool(row.get("analysis_pending_llm")) or "pending" in str(row.get("analysis_agent", ""))
    low_information = len(summary) < 160 or summary.lower() in {"摘要未披露", ""}
    if pending and (score <= 0.0 or low_information):
        return False
    if source_type in {"blog", "research_blog", "blog_mashup"}:
        lowered = text.lower()
        quality_terms = (
            "backtest",
            "backtesting",
            "empirical",
            "out-of-sample",
            "walk-forward",
            "sharpe",
            "factor",
            "anomaly",
            "portfolio",
            "strategy",
            "regression",
            "sample",
            "data",
            "回测",
            "样本",
            "实证",
            "因子",
            "策略",
        )
        if low_information and not any(term in lowered for term in quality_terms):
            return False
    return True


def read_jsonl(path: Path) -> List[Dict[str, object]]:
    from src.io.jsonl import read_jsonl as _read_jsonl

    return _read_jsonl(path)


def write_jsonl(path: Path, rows: List[Dict[str, object]]) -> None:
    from src.io.jsonl import write_jsonl as _write_jsonl

    _write_jsonl(path, rows)


def _split_sentences(text: str) -> List[str]:
    text = _normalize_text(text)
    if not text:
        return []
    return [x.strip() for x in re.split(r"(?<=[\.\!\?。；;])\s+", text) if x.strip()]


def _clamp_score(value: object) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        score = 0
    return max(0, min(10, score))


def _normalize_dimension_scores(raw: object) -> Dict[str, Dict[str, object]]:
    payload = raw if isinstance(raw, dict) else {}
    normalized: Dict[str, Dict[str, object]] = {}
    for key, label in SCORE_DIMENSIONS:
        item = payload.get(key, {})
        if not isinstance(item, dict):
            item = {}
        normalized[key] = {
            "label": label,
            "score": _clamp_score(item.get("score", 0)),
            "comment": _normalize_text(str(item.get("comment", "")))[:520],
            "evidence": _normalize_text(str(item.get("evidence", "")))[:260],
            "critique": _normalize_text(str(item.get("critique", "")))[:520],
        }
    return normalized


def _normalize_structured_summary(raw: object) -> Dict[str, str]:
    payload = raw if isinstance(raw, dict) else {}
    fields = (
        ("problem", "问题"),
        ("method", "方法"),
        ("data", "数据"),
        ("author_claim", "作者主张"),
        ("limitations", "局限"),
        ("critical_assessment", "批判性评估"),
        ("missing_tests", "缺失验证"),
        ("key_results", "关键结果"),
    )
    return {
        key: _normalize_text(str(payload.get(key, "")))[:900]
        for key, _label in fields
        if _normalize_text(str(payload.get(key, "")))
    }


def _heuristic_structured_summary(title: str, summary: str, tags: List[str]) -> Dict[str, str]:
    content = _normalize_text(summary or title)
    tag_text = "、".join(tags) if tags else "摘要未披露"
    method_markers = [
        "model",
        "approach",
        "framework",
        "method",
        "algorithm",
        "estimat",
        "simulation",
        "regression",
        "模型",
        "方法",
        "框架",
        "估计",
        "仿真",
        "回归",
    ]
    result_markers = [
        "outperform",
        "significant",
        "sharpe",
        "return",
        "accuracy",
        "evidence",
        "result",
        "%",
        "结果",
        "显著",
        "收益",
        "精度",
    ]
    sentences = _split_sentences(content)

    def pick(markers: List[str], fallback: str) -> str:
        for sentence in sentences:
            lowered_sentence = sentence.lower()
            if any(marker.lower() in lowered_sentence for marker in markers):
                return sentence[:360]
        return fallback

    return {
        "problem": f"围绕《{title}》讨论的研究问题，摘要显示其与{tag_text}相关；完整问题定义需 LLM 或正文进一步判读。",
        "method": pick(method_markers, "摘要未披露明确方法细节；当前只能从标题、摘要关键词和来源标签做保守归纳。"),
        "data": "摘要未披露明确样本区间、标的池或频率；若来源为博客/教程，通常需要正文页面补充数据设定。",
        "author_claim": pick(result_markers, "摘要未披露作者明确主张；需要正文确认其声称解决的市场或建模问题。"),
        "limitations": "摘要信息有限，无法可靠判断模型假设、样本外稳定性、交易成本与字段可得性；需 LLM 阅读正文或更长摘要后确认。",
        "critical_assessment": "当前只能做保守批判：若没有正文中的实验设计、稳健性表格和交易成本假设，不能把摘要结论直接视为可交易 alpha。",
        "missing_tests": "需要补充样本外检验、滚动窗口稳定性、交易成本后收益、不同市场状态分层和可实现字段检查。",
        "key_results": pick(result_markers, "摘要未披露明确 Sharpe、IC、收益、显著性或样本规模等关键结果。"),
    }


def _mean_recommendation_score(score_dimensions: Dict[str, Dict[str, object]]) -> float:
    scores = [float(v["score"]) for v in score_dimensions.values()]
    return round(sum(scores) / len(scores), 1) if scores else 0.0


def _format_score(score: object) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        value = 0.0
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.1f}"


def _safe_factor_field(value: object, fallback: str) -> str:
    raw = str(value or "").strip().lower()
    raw = re.sub(r"[^0-9a-zA-Z_]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    if not raw:
        raw = fallback
    if raw[0].isdigit():
        raw = f"factor_{raw}"
    return raw[:80]


def _normalize_string_list(raw: object, limit: int = 12) -> List[str]:
    if isinstance(raw, list):
        return [_normalize_text(str(x))[:80] for x in raw if _normalize_text(str(x))][:limit]
    if isinstance(raw, str) and raw.strip():
        return [_normalize_text(raw)[:80]]
    return []


def _load_mechanism_taxonomy(path: Path = DEFAULT_MECHANISM_TAXONOMY_PATH) -> List[Dict[str, object]]:
    global _MECHANISM_TAXONOMY_CACHE
    if _MECHANISM_TAXONOMY_CACHE is not None:
        return _MECHANISM_TAXONOMY_CACHE
    if not path.exists():
        _MECHANISM_TAXONOMY_CACHE = []
        return _MECHANISM_TAXONOMY_CACHE
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    categories = payload.get("categories") if isinstance(payload, dict) else []
    _MECHANISM_TAXONOMY_CACHE = [item for item in categories if isinstance(item, dict)] if isinstance(categories, list) else []
    return _MECHANISM_TAXONOMY_CACHE


def _mechanism_taxonomy_context(
    *,
    title: str,
    summary: str,
    tags: List[str],
    evidence_pack: Dict[str, object],
    limit: int = MECHANISM_TAXONOMY_CONTEXT_LIMIT,
) -> List[Dict[str, str]]:
    text_parts = [title, summary, " ".join(tags)]
    for key in ("section_overview", "intro_context", "formula_contexts", "method_blocks", "empirical_setup_snippets"):
        value = evidence_pack.get(key)
        if isinstance(value, str):
            text_parts.append(value)
        elif isinstance(value, list):
            text_parts.append(json.dumps(value, ensure_ascii=False)[:4000])
    haystack = _normalize_text(" ".join(text_parts)).lower()
    ranked: List[Tuple[int, int, Dict[str, object]]] = []
    for idx, item in enumerate(_load_mechanism_taxonomy()):
        keywords = _normalize_string_list(item.get("keywords"), limit=100)
        score = sum(1 for keyword in keywords if keyword.lower() in haystack)
        ranked.append((score, -idx, item))
    ranked.sort(reverse=True, key=lambda entry: (entry[0], entry[1]))
    selected = [item for score, _idx, item in ranked if score > 0][:limit]
    if len(selected) < limit:
        selected_ids = {str(item.get("id") or "") for item in selected}
        for _score, _idx, item in ranked:
            item_id = str(item.get("id") or "")
            if item_id not in selected_ids:
                selected.append(item)
                selected_ids.add(item_id)
            if len(selected) >= limit:
                break
    return [
        {
            "id": str(item.get("id") or "other"),
            "title_zh": str(item.get("title_zh") or ""),
            "title_en": str(item.get("title_en") or ""),
            "original_derivation": str(item.get("original_derivation") or ""),
            "proxy_mapping": str(item.get("proxy_mapping") or ""),
            "standard_operator": str(item.get("standard_operator") or ""),
        }
        for item in selected
    ]


def _evidence_source_anchor(evidence_pack: Dict[str, object]) -> Dict[str, str]:
    return {
        "source_file": str(evidence_pack.get("main_source_file") or ""),
        "source_kind": str(evidence_pack.get("source_kind") or ""),
    }


def _classify_intro_claim(sentence: str) -> str:
    lowered = sentence.lower()
    if re.search(r"\b(problem|question|puzzle|challenge|why|whether)\b|问题|挑战|是否", lowered):
        return "problem"
    if re.search(r"\b(mechanism|because|channel|effect|impact|drives?|causes?)\b|机制|渠道|影响|导致", lowered):
        return "mechanism_claim"
    if re.search(r"\b(contribution|we show|we find|we propose|we develop|result)\b|贡献|发现|提出|结果", lowered):
        return "contribution"
    if re.search(r"\b(data|sample|period|frequency|stock|market|portfolio|regression)\b|数据|样本|频率|市场|组合|回归", lowered):
        return "data_or_setup"
    return "claim"


def _intro_claims_from_evidence(evidence_pack: Dict[str, object], limit: int = 8) -> List[Dict[str, str]]:
    anchor = _evidence_source_anchor(evidence_pack)
    claims: List[Dict[str, str]] = []
    for sentence in _split_sentences(str(evidence_pack.get("intro_context") or "")):
        clean = _normalize_text(sentence)
        if len(clean) < 40:
            continue
        claims.append({
            "type": _classify_intro_claim(clean),
            "text": clean[:420],
            "section": "Introduction",
            "evidence_type": "intro_claim",
            **anchor,
        })
        if len(claims) >= limit:
            break
    return claims


def _formula_evidence_from_pack(evidence_pack: Dict[str, object], limit: int = 6) -> List[Dict[str, object]]:
    anchor = _evidence_source_anchor(evidence_pack)
    raw = str(evidence_pack.get("formula_contexts") or "")
    blocks = [part.strip() for part in raw.split("\n\n---\n\n") if part.strip()]
    out: List[Dict[str, object]] = []
    stop_words = {"begin", "end", "label", "frac", "left", "right", "text", "sum", "mathbb", "mathrm"}
    for block in blocks[:limit]:
        tex_lines = [line.strip() for line in block.splitlines() if line.strip()]
        formula_lines = [line for line in tex_lines if "$" in line or "\\begin{" in line or "\\end{" in line or "=" in line]
        formula = "\n".join(formula_lines[:12]) or block[:900]
        explanation = _strip_tex_commands(" ".join(line for line in tex_lines if line not in formula_lines))
        variable_candidates = re.findall(r"(?<![A-Za-z])([A-Za-z][A-Za-z0-9_]*(?:_\{?[A-Za-z0-9]+\}?)?)(?![A-Za-z])", formula)
        variables = [item for item in dict.fromkeys(variable_candidates) if item.lower() not in stop_words]
        out.append({
            "formula": formula[:1200],
            "nearby_explanation": explanation[:700],
            "variables": variables[:16],
            "section": "formula_context",
            "proxy_hint": "derive_from_formula_and_variable_roles",
            "evidence_type": "formula_context",
            **anchor,
        })
    return out


def _variable_definitions_from_pack(evidence_pack: Dict[str, object], limit: int = 12) -> List[Dict[str, str]]:
    anchor = _evidence_source_anchor(evidence_pack)
    text_parts: List[str] = []
    for key in ("formula_contexts", "intro_context"):
        value = evidence_pack.get(key)
        if isinstance(value, str):
            text_parts.append(value)
    for block in evidence_pack.get("method_blocks") if isinstance(evidence_pack.get("method_blocks"), list) else []:
        if isinstance(block, dict):
            text_parts.append(str(block.get("text") or ""))
    text = _strip_tex_commands(" ".join(text_parts))
    patterns = (
        r"\b([A-Za-z][A-Za-z0-9_]{0,24})\s+(?:is|are|denotes?|measures?|captures?|represents?)\s+([^\.。;；]{20,260})",
        r"\bwhere\s+([A-Za-z][A-Za-z0-9_]{0,24})\s+(?:is|denotes?|measures?|captures?|represents?)\s+([^\.。;；]{20,260})",
        r"\b([A-Za-z][A-Za-z0-9_]{0,24})\s+is\s+defined\s+as\s+([^\.。;；]{20,260})",
    )
    definitions: List[Dict[str, str]] = []
    seen = set()
    for pattern in patterns:
        for name, definition in re.findall(pattern, text, flags=re.I):
            norm_name = name.strip()
            if norm_name.lower() in seen or norm_name.lower() in {"this", "that", "there", "which", "model", "paper", "result"}:
                continue
            seen.add(norm_name.lower())
            definitions.append({
                "name": norm_name,
                "definition": _normalize_text(definition)[:360],
                "observable": "unknown_from_input",
                "local_proxy_candidate": "LLM must infer only from available local fields or mark unobservable",
                "evidence_type": "variable_definition",
                **anchor,
            })
            if len(definitions) >= limit:
                return definitions
    return definitions


def _method_and_empirical_evidence(evidence_pack: Dict[str, object]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]]]:
    anchor = _evidence_source_anchor(evidence_pack)
    method_evidence: List[Dict[str, str]] = []
    data_sample_evidence: List[Dict[str, str]] = []
    empirical_results: List[Dict[str, str]] = []
    for block in evidence_pack.get("method_blocks") if isinstance(evidence_pack.get("method_blocks"), list) else []:
        if not isinstance(block, dict):
            continue
        section = str(block.get("section") or "method")
        text = _normalize_text(str(block.get("text") or ""))[:900]
        if not text:
            continue
        method_evidence.append({"section": section, "text": text, "evidence_type": "method_evidence", **anchor})
        if re.search(r"\b(data|sample|period|frequency|stock|asset|filter|universe|portfolio|rebalance)\b|数据|样本|频率|股票|资产|筛选|组合", text, flags=re.I):
            data_sample_evidence.append({"section": section, "text": text, "evidence_type": "data_sample_evidence", **anchor})
    for block in evidence_pack.get("empirical_setup_snippets") if isinstance(evidence_pack.get("empirical_setup_snippets"), list) else []:
        if not isinstance(block, dict):
            continue
        section = str(block.get("section") or "empirical_setup")
        text = _normalize_text(str(block.get("text") or ""))[:700]
        if not text:
            continue
        data_sample_evidence.append({"section": section, "text": text, "evidence_type": "data_sample_evidence", **anchor})
        if re.search(r"\b(result|return|alpha|spread|t-stat|statistic|significant|performance|Sharpe|bp|basis point)\b|结果|收益|显著|统计|基点", text, flags=re.I):
            empirical_results.append({"claim": text, "stat": "extract_if_disclosed", "section": section, "evidence_type": "empirical_result", **anchor})
    return method_evidence[:5], data_sample_evidence[:6], empirical_results[:5]


def _list_block_evidence_from_pack(evidence_pack: Dict[str, object], source_key: str, evidence_type: str, *, limit: int = 6, text_limit: int = 900) -> List[Dict[str, str]]:
    anchor = _evidence_source_anchor(evidence_pack)
    out: List[Dict[str, str]] = []
    value = evidence_pack.get(source_key)
    if isinstance(value, str):
        blocks = [part.strip() for part in value.split("\n\n---\n\n") if part.strip()]
        for idx, block in enumerate(blocks[:limit], start=1):
            out.append({"section": f"{source_key}_{idx}", "text": _normalize_text(block)[:text_limit], "evidence_type": evidence_type, **anchor})
        return out
    if not isinstance(value, list):
        return out
    for item in value[:limit]:
        if isinstance(item, dict):
            section = str(item.get("section") or source_key)
            text = _normalize_text(str(item.get("text") or ""))[:text_limit]
            item_type = str(item.get("evidence_type") or evidence_type)
        else:
            section = source_key
            text = _normalize_text(str(item or ""))[:text_limit]
            item_type = evidence_type
        if text:
            out.append({"section": section, "text": text, "evidence_type": item_type, **anchor})
    return out


def _missing_evidence_from_pack(evidence_pack: Dict[str, object]) -> Dict[str, str]:
    text_parts = [str(evidence_pack.get(key) or "") for key in ("section_overview", "intro_context", "formula_contexts", "experimental_formula_contexts")]
    for key in ("method_blocks", "empirical_setup_snippets", "conclusion_context", "code_or_algorithm_snippets"):
        value = evidence_pack.get(key)
        if isinstance(value, list):
            text_parts.append(json.dumps(value, ensure_ascii=False))
    haystack = _normalize_text(" ".join(text_parts)).lower()

    def marker(pattern: str) -> str:
        return "输入包含相关片段，需LLM逐条核验" if re.search(pattern, haystack, flags=re.I) else "输入未披露"

    return {
        "transaction_cost": marker(r"transaction cost|trading cost|fee|slippage|bid[- ]ask|spread|成本|滑点|手续费"),
        "out_of_sample": marker(r"out[- ]of[- ]sample|holdout|validation|walk[- ]forward|样本外|验证集"),
        "capacity": marker(r"capacity|turnover|liquidity constraint|market impact|容量|换手|冲击成本"),
        "statistical_tests": marker(r"t[- ]stat|p[- ]value|confidence|standard error|significant|显著|标准误|置信"),
        "implementation_fields": marker(r"order book|limit order book|volume|price|return|spread|depth|queue|订单簿|盘口|成交量|价格|收益|价差|深度"),
    }


def build_evidence_pack_v2(evidence_pack: Dict[str, object]) -> Dict[str, object]:
    if not evidence_pack:
        return {}
    method_evidence, data_sample_evidence, empirical_results = _method_and_empirical_evidence(evidence_pack)
    section_map = []
    anchor = _evidence_source_anchor(evidence_pack)
    for line in str(evidence_pack.get("section_overview") or "").splitlines()[:16]:
        heading = _normalize_text(line.lstrip("- "))
        if heading:
            section_map.append({"heading": heading[:180], "evidence_type": "section_map", **anchor})
    return {
        "quality": evidence_pack.get("quality_checks") if isinstance(evidence_pack.get("quality_checks"), dict) else {},
        "section_map": section_map,
        "intro_claims": _intro_claims_from_evidence(evidence_pack),
        "formula_evidence": _formula_evidence_from_pack(evidence_pack),
        "variable_definitions": _variable_definitions_from_pack(evidence_pack),
        "method_evidence": method_evidence,
        "data_sample_evidence": data_sample_evidence,
        "empirical_results": empirical_results,
        "experimental_formula_evidence": _list_block_evidence_from_pack(evidence_pack, "experimental_formula_contexts", "experimental_formula_context", limit=6, text_limit=1200),
        "code_evidence": _list_block_evidence_from_pack(evidence_pack, "code_or_algorithm_snippets", "code_or_algorithm_evidence", limit=6, text_limit=900),
        "conclusion_evidence": _list_block_evidence_from_pack(evidence_pack, "conclusion_context", "conclusion_or_limit_evidence", limit=4, text_limit=1200),
        "missing_evidence": _missing_evidence_from_pack(evidence_pack),
        "excluded_sections": str(evidence_pack.get("excluded_sections") or "references/appendix"),
    }


def _registry_aliases(raw_aliases: object, *, include_suggested: bool = False) -> List[str]:
    if isinstance(raw_aliases, dict):
        values: List[str] = []
        keys = ("confirmed", "suggested") if include_suggested else ("confirmed",)
        for key in keys:
            values.extend(_normalize_string_list(raw_aliases.get(key), limit=200))
        return list(dict.fromkeys(values))
    return _normalize_string_list(raw_aliases, limit=200)


def _candidate_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = _normalize_text(value)
    if not text or text.startswith("[") or text.startswith("{"):
        return ""
    return text


def _normalize_paper_hf_formula_plan(raw: object) -> Dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    template_id = _safe_factor_field(raw.get("template_id") or raw.get("template"), "unknown_template") if raw.get("template_id") or raw.get("template") else ""
    fallback_template = _safe_factor_field(raw.get("fallback_template"), "unknown_template") if raw.get("fallback_template") else ""
    operator_family = _safe_factor_field(raw.get("operator_family") or raw.get("operator"), "unknown_operator") if raw.get("operator_family") or raw.get("operator") else ""
    raw_windows = raw.get("windows") or []
    windows: List[int] = []
    if isinstance(raw_windows, list):
        for item in raw_windows[:6]:
            try:
                value = int(item)
            except (TypeError, ValueError):
                continue
            if 1 <= value <= 3900:
                windows.append(value)
    normalization = _safe_factor_field(raw.get("normalization"), "unknown_normalization") if raw.get("normalization") else ""
    direction = _safe_factor_field(raw.get("direction"), "unknown_direction") if raw.get("direction") else ""
    custom_formula = _normalize_text(str(raw.get("custom_formula") or ""))[:900]
    custom_formula_prefix = _normalize_text(str(raw.get("custom_formula_prefix") or raw.get("prefix_formula") or ""))[:900]
    custom_formula_rationale = _normalize_text(str(raw.get("custom_formula_rationale") or raw.get("rationale") or raw.get("reason") or ""))[:500]
    complexity_evidence = _normalize_text(str(raw.get("complexity_evidence") or ""))[:500]
    nonlinear_mechanism = _normalize_text(str(raw.get("nonlinear_mechanism") or ""))[:500]
    raw_hf_formula = _normalize_text(str(raw.get("raw_hf_formula") or ""))[:700]
    raw_hf_logic = _normalize_text(str(raw.get("raw_hf_logic") or ""))[:900]
    synthesis_agent = _normalize_text(str(raw.get("synthesis_agent") or ""))[:120]
    validation_status = _normalize_text(str(raw.get("validation_status") or ""))[:80]
    validation_error = _normalize_text(str(raw.get("validation_error") or ""))[:260]
    return {
        key: value
        for key, value in {
            "template_id": template_id,
            "fallback_template": fallback_template,
            "operator_family": operator_family,
            "inputs": _normalize_string_list(raw.get("inputs") or raw.get("input_fields"), limit=16),
            "proxy_variable_keys": _normalize_string_list(raw.get("proxy_variable_keys") or raw.get("used_proxy_variables"), limit=24),
            "used_proxy_variables": _normalize_string_list(raw.get("used_proxy_variables"), limit=24),
            "windows": windows,
            "normalization": normalization,
            "direction": direction,
            "rationale": _normalize_text(str(raw.get("rationale") or raw.get("reason") or ""))[:300],
            "custom_formula": custom_formula,
            "custom_formula_prefix": custom_formula_prefix,
            "custom_formula_rationale": custom_formula_rationale,
            "complexity_evidence": complexity_evidence,
            "nonlinear_mechanism": nonlinear_mechanism,
            "raw_hf_formula": raw_hf_formula,
            "raw_hf_logic": raw_hf_logic,
            "synthesis_agent": synthesis_agent,
            "validation_status": validation_status,
            "validation_error": validation_error,
        }.items()
        if value
    }


def normalize_paper_hf_factors(raw_factors: object) -> List[Dict[str, object]]:
    if not isinstance(raw_factors, list):
        return []

    factors: List[Dict[str, object]] = []
    for idx, item in enumerate(raw_factors, start=1):
        if isinstance(item, str):
            meaning = _normalize_text(item)[:700]
            if not meaning:
                continue
            factors.append(
                {
                    "name": f"论文高频因子 {idx}",
                    "frequency": "待定",
                    "mechanism_category": "other",
                    "mechanism_type": "unknown",
                    "mechanism_formula": "",
                    "paper_hf_formula_plan": {},
                    "meaning": meaning,
                    "ideal_input_fields": [],
                    "variable_roles": [],
                    "paper_mechanism": meaning,
                    "source_evidence": "",
                    "formula_source_type": "unknown",
                    "formula_source_quote": "",
                    "novelty_reason": "",
                    "classic_baseline": "",
                    "unobservable_variables": [],
                    "minimum_data_needed": [],
                }
            )
            continue
        if not isinstance(item, dict):
            continue

        name = _candidate_text(item.get("name"))[:120]
        frequency = _normalize_text(str(item.get("frequency") or item.get("horizon") or "待定"))[:80]
        mechanism_category = _normalize_text(str(item.get("mechanism_category") or item.get("paper_category") or item.get("category") or "other"))[:80]
        mechanism_type = _normalize_text(str(item.get("mechanism_type") or item.get("factor_type") or "unknown"))[:80]
        mechanism_formula = _normalize_text(str(item.get("mechanism_formula") or item.get("formula") or ""))[:520]
        paper_hf_formula_plan = _normalize_paper_hf_formula_plan(item.get("paper_hf_formula_plan") or item.get("formula_plan") or {})
        meaning = _normalize_text(str(item.get("meaning") or item.get("rationale") or item.get("description") or item.get("procedure") or ""))[:700]
        ideal_input_fields = _normalize_string_list(item.get("ideal_input_fields") or item.get("input_fields") or item.get("inputs"), limit=24)
        variable_roles_raw = item.get("variable_roles") or item.get("roles") or []
        variable_roles = []
        if isinstance(variable_roles_raw, list):
            for role in variable_roles_raw[:24]:
                if isinstance(role, dict):
                    variable = _normalize_text(str(role.get("variable") or role.get("name") or ""))[:80]
                    role_name = _normalize_text(str(role.get("role") or role.get("purpose") or ""))[:120]
                    if variable or role_name:
                        variable_roles.append({"variable": variable, "role": role_name})
                elif role:
                    variable_roles.append({"variable": _normalize_text(str(role))[:80], "role": ""})
        procedure = _normalize_text(str(item.get("procedure") or item.get("calculation_steps") or ""))[:900]
        rationale = _normalize_text(str(item.get("rationale") or ""))[:700]
        paper_mechanism = _normalize_text(str(item.get("paper_mechanism") or item.get("mechanism") or rationale or meaning))[:900]
        source_evidence = _normalize_text(str(item.get("source_evidence") or item.get("evidence") or ""))[:260]
        source_seed_factor_id = _normalize_text(str(item.get("source_seed_factor_id") or item.get("source_seed_id") or ""))[:80]
        formula_source_type = _normalize_text(str(item.get("formula_source_type") or item.get("formula_origin") or item.get("source_type") or "unknown"))[:80]
        if formula_source_type == "paper_formula":
            formula_source_type = "final_model_formula"
        if formula_source_type not in {"final_model_formula", "intermediate_definition", "estimation_procedure", "result_statement", "mechanism_derived", "llm_proxy_mapping", "unknown"}:
            formula_source_type = "unknown"
        formula_source_quote = _normalize_text(str(item.get("formula_source_quote") or item.get("formula_evidence") or item.get("source_quote") or ""))[:700]
        formula_role_in_paper = _normalize_text(str(item.get("formula_role_in_paper") or item.get("formula_role") or "unknown"))[:80]
        if formula_role_in_paper not in {"final_mechanism", "setup_definition", "calibration_step", "robustness_result", "empirical_decomposition", "proxy_mapping", "unknown"}:
            formula_role_in_paper = "unknown"
        why_this_formula_is_actionable = _normalize_text(str(item.get("why_this_formula_is_actionable") or item.get("actionability_rationale") or ""))[:700]
        whole_paper_formula = _normalize_text(str(item.get("whole_paper_formula") or ""))[:700]
        raw_whole_paper_basis = item.get("whole_paper_basis") if isinstance(item.get("whole_paper_basis"), dict) else {}
        whole_paper_basis = {
            "problem": _normalize_text(str(raw_whole_paper_basis.get("problem") or ""))[:220],
            "method": _normalize_text(str(raw_whole_paper_basis.get("method") or ""))[:220],
            "final_result_or_formula": _normalize_text(str(raw_whole_paper_basis.get("final_result_or_formula") or ""))[:220],
            "limitations_or_data": _normalize_text(str(raw_whole_paper_basis.get("limitations_or_data") or ""))[:220],
        }
        novelty_reason = _normalize_text(str(item.get("novelty_reason") or item.get("novelty") or ""))[:520]
        classic_baseline = _normalize_text(str(item.get("classic_baseline") or item.get("baseline") or ""))[:260]
        unobservable_variables = _normalize_string_list(item.get("unobservable_variables") or item.get("missing_variables") or [], limit=24)
        minimum_data_needed = _normalize_string_list(item.get("minimum_data_needed") or item.get("data_needed") or [], limit=24)
        proxy_variants_v2 = item.get("proxy_variants_v2") if isinstance(item.get("proxy_variants_v2"), list) else []
        proxy_mappings = item.get("proxy_mappings") if isinstance(item.get("proxy_mappings"), list) else []
        unresolved_proxy_variables = _normalize_string_list(item.get("unresolved_proxy_variables") or [], limit=24)
        proxy_status = _normalize_text(str(item.get("proxy_status") or ""))[:80]
        proxy_status_reason = _normalize_text(str(item.get("proxy_status_reason") or ""))[:260]
        if not name:
            name = f"论文高频因子 {idx}"
        if not meaning and paper_mechanism:
            meaning = paper_mechanism
        if not meaning:
            continue
        factors.append(
            {
                "name": name,
                "frequency": frequency or "待定",
                "mechanism_category": mechanism_category or "other",
                "mechanism_type": mechanism_type or "unknown",
                "mechanism_formula": mechanism_formula,
                "paper_hf_formula_plan": paper_hf_formula_plan,
                "meaning": meaning,
                "ideal_input_fields": ideal_input_fields,
                "variable_roles": variable_roles,
                "paper_mechanism": paper_mechanism or meaning,
                "source_evidence": source_evidence,
                "source_seed_factor_id": source_seed_factor_id,
                "formula_source_type": formula_source_type,
                "formula_source_quote": formula_source_quote,
                "formula_role_in_paper": formula_role_in_paper,
                "why_this_formula_is_actionable": why_this_formula_is_actionable,
                "whole_paper_formula": whole_paper_formula,
                "whole_paper_basis": whole_paper_basis,
                "novelty_reason": novelty_reason,
                "classic_baseline": classic_baseline,
                "unobservable_variables": unobservable_variables,
                "minimum_data_needed": minimum_data_needed,
                "procedure": procedure,
                "rationale": rationale,
                "proxy_mappings": proxy_mappings,
                "proxy_status": proxy_status,
                "proxy_status_reason": proxy_status_reason,
                "unresolved_proxy_variables": unresolved_proxy_variables,
                "proxy_variants_v2": proxy_variants_v2,
            }
        )
    return factors[:PAPER_HF_FACTOR_LIMIT]


def _paper_factors_for_row(row: Dict[str, object]) -> List[Dict[str, object]]:
    factors = normalize_paper_hf_factors(row.get("paper_hf_factors", []))
    if factors:
        return factors
    return normalize_paper_hf_factors(row.get("hf_factor_points", []))


def _strict_paper_hf_factors_for_row(row: Dict[str, object]) -> List[Dict[str, object]]:
    return normalize_paper_hf_factors(row.get("paper_hf_factors", []))


def _has_future_return_reference(value: object) -> bool:
    return bool(FUTURE_RETURN_RE.search(str(value or "")))


def _is_low_information_candidate(template: str, required_fields: List[str], expression: str) -> bool:
    fields = set(required_fields)
    compact_expression = re.sub(r"\s+", "", expression.lower())
    pure_l1_obi = fields and fields.issubset({"bidV1", "askV1"}) and fields == {"bidV1", "askV1"}
    expression_is_l1_obi = compact_expression in {
        "(bidv1-askv1)/(bidv1+askv1)",
        "(bidv1-askv1)/(bidv1+askv1+1e-9)",
        "(bidv1-askv1)/(bidv1+askv1+1e-6)",
    }
    return template in {"order_book_imbalance", "depth_pressure", "volume_pressure"} and (
        pure_l1_obi or expression_is_l1_obi
    )


def _template_support_problem(template: str, required_fields: List[str]) -> str:
    fields = set(required_fields)
    if template in {"order_book_imbalance", "depth_pressure", "volume_pressure"}:
        has_depth_pair = any({f"bidV{level}", f"askV{level}"}.issubset(fields) for level in range(1, 11))
        has_total_depute = {"totalDeputeBuy", "totalDeputeSell"}.issubset(fields)
        if not (has_depth_pair or has_total_depute):
            return "盘口压力类模板至少需要成对 bidV/askV 档位或 totalDeputeBuy/totalDeputeSell。"
    if template == "bid_ask_spread":
        has_price_pair = any({f"bidP{level}", f"askP{level}"}.issubset(fields) for level in range(1, 11))
        if not has_price_pair:
            return "价差模板至少需要成对 bidP/askP 档位。"
    if template == "weighted_mid_price_deviation" and not {"bidP1", "askP1", "bidV1", "askV1", "close"}.issubset(fields):
        return "加权中价偏离模板需要 bidP1/askP1/bidV1/askV1/close。"
    if template == "trade_intensity" and "volume" not in fields:
        return "成交强度模板需要 volume。"
    if template == "money_flow" and not {"money", "volume"}.issubset(fields):
        return "资金流模板需要 money 和 volume。"
    if template in {"short_return_momentum", "short_return_reversal"} and "close" not in fields:
        return "短窗收益模板需要 close。"
    return ""


def _candidate_mechanism_support_problem(
    proxy_mappings: List[Dict[str, object]],
    required_fields: List[str],
    expression: str,
) -> str:
    canonical = {str(mapping.get("canonical_variable") or "") for mapping in proxy_mappings}
    fields = set(required_fields)
    compact_expression = _canonicalize_proxy_name(expression)
    depth_fields = {f"bidV{level}" for level in range(1, 11)} | {f"askV{level}" for level in range(1, 11)}
    price_fields = {f"bidP{level}" for level in range(1, 11)} | {f"askP{level}" for level in range(1, 11)}
    if "order_book_imbalance" in canonical or "lob_state_divergence" in canonical:
        if not (fields & depth_fields or {"totalDeputeBuy", "totalDeputeSell"}.issubset(fields)):
            return "候选声明订单簿/盘口失衡代理，但表达式没有使用盘口深度字段。"
    if "execution_friction" in canonical:
        if not (fields & price_fields and {"ask", "bid"}.issubset(set(re.findall(r"ask|bid", expression, flags=re.I)))):
            return "候选声明价差/执行摩擦代理，但表达式没有同时使用买卖报价。"
    if "volume_or_trade_activity" in canonical:
        if not (fields & {"volume", "money", "totalDeputeBuy", "totalDeputeSell"} or fields & depth_fields):
            return "候选声明成交/活动强度代理，但表达式没有使用量能、金额或深度字段。"
    if "realized_volatility" in canonical:
        if not any(token in compact_expression for token in ("rollingstd", "abs", "diff", "pctchange")):
            return "候选声明波动率代理，但表达式没有滚动波动、差分或收益幅度结构。"
    if "return_series" in canonical:
        if not any(token in compact_expression for token in ("pctchange", "lastclose", "diff", "close", "askp1", "bidp1")):
            return "候选声明收益序列代理，但表达式没有价格变化结构。"
    return ""


def _canonicalize_proxy_name(value: object) -> str:
    text = html.unescape(_normalize_text(str(value or ""))).lower()
    text = text.replace("γ", "gamma").replace("σ", "sigma").replace("κ", "kappa")
    text = re.sub(r"\b(best|top|level|lvl)\b", "", text)
    text = re.sub(r"\b(series|value|feature|factor|signal)\b", "", text)
    text = re.sub(r"(?:^|[_\s\-])t$", "", text)
    return re.sub(r"[^0-9a-z]+", "", text)


def _load_proxy_registry(path: Path = DEFAULT_PROXY_REGISTRY_PATH) -> Dict[str, object]:
    global _PROXY_REGISTRY_CACHE
    if _PROXY_REGISTRY_CACHE is not None:
        return _PROXY_REGISTRY_CACHE
    if not path.exists():
        _PROXY_REGISTRY_CACHE = {"variables": {}, "aliases": {}, "exact_aliases": {}}
        return _PROXY_REGISTRY_CACHE
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    variables = payload.get("variables", {}) if isinstance(payload, dict) else {}
    if not isinstance(variables, dict):
        variables = {}
    aliases: Dict[str, str] = {}
    exact_aliases: Dict[str, str] = {}
    for canonical, raw_meta in variables.items():
        if not isinstance(raw_meta, dict):
            continue
        names = [str(canonical), *_registry_aliases(raw_meta.get("aliases", []))]
        for name in names:
            exact_key = _normalize_text(str(name)).lower()
            if exact_key:
                exact_aliases[exact_key] = str(canonical)
            key = _canonicalize_proxy_name(name)
            if key:
                aliases[key] = str(canonical)
    mechanism_catalog = payload.get("mechanism_catalog", {}) if isinstance(payload, dict) else {}
    if not isinstance(mechanism_catalog, dict):
        mechanism_catalog = {}
    _PROXY_REGISTRY_CACHE = {
        "variables": variables,
        "aliases": aliases,
        "exact_aliases": exact_aliases,
        "mechanism_catalog": mechanism_catalog,
    }
    return _PROXY_REGISTRY_CACHE


def _proxy_strength_rank(strength: str) -> int:
    order = {"direct": 0, "derived": 1, "weak_proxy": 2, "future_pipeline": 3, "unsupported": 4}
    return order.get(strength, 4)


def _validate_registry_proxy(proxy: Dict[str, object]) -> Tuple[str, str]:
    expression = str(proxy.get("expression") or "").strip()
    if not expression:
        return "not_configured", "missing expression"
    missing_fields = [field for field in _normalize_string_list(proxy.get("required_fields"), limit=32) if field not in ALLOWED_FACTOR_FIELDS]
    if missing_fields:
        return "future_pipeline", "unsupported fields: " + ", ".join(missing_fields[:8])
    allowed_functions = _normalize_string_list(proxy.get("allowed_functions"), limit=24)
    unknown_functions = [func for func in allowed_functions if func not in ALLOWED_EXPRESSION_FUNCS]
    if unknown_functions:
        return "future_pipeline", "unsupported functions: " + ", ".join(unknown_functions[:8])
    if _compile_llm_expression(expression) is None:
        return "future_pipeline", "expression failed current whitelist validation"
    return "executable", ""


def _proxy_mapping_from_registry(canonical: str, raw_variable: str) -> Dict[str, object]:
    registry = _load_proxy_registry()
    variables = registry.get("variables", {})
    meta = variables.get(canonical, {}) if isinstance(variables, dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    strength = str(meta.get("proxy_strength") or "unsupported")
    if strength not in PROXY_STRENGTHS:
        strength = "unsupported"
    raw_proxies: List[object] = []
    raw_conditional_proxies = meta.get("conditional_proxies", [])
    raw_context = _canonicalize_proxy_name(raw_variable)
    if isinstance(raw_conditional_proxies, list) and raw_context:
        for raw_proxy in raw_conditional_proxies:
            if not isinstance(raw_proxy, dict):
                continue
            when_context = str(raw_proxy.get("when_context") or "")
            if when_context and _canonicalize_proxy_name(when_context) in raw_context:
                proxy_with_context = dict(raw_proxy)
                proxy_with_context["context_match"] = True
                raw_proxies.append(proxy_with_context)
    default_proxies = meta.get("local_proxies", [])
    if isinstance(default_proxies, list):
        raw_proxies.extend(default_proxies)
    quality_rank = {"high": 0, "medium": 1, "low": 2}
    local_proxies: List[Dict[str, object]] = []
    if isinstance(raw_proxies, list):
        for raw_proxy in raw_proxies:
            if not isinstance(raw_proxy, dict):
                continue
            proxy_quality = str(raw_proxy.get("proxy_quality") or "medium")
            if proxy_quality not in quality_rank:
                proxy_quality = "medium"
            proxy = {
                "expression": _normalize_text(str(raw_proxy.get("expression") or ""))[:520],
                "required_fields": _normalize_string_list(raw_proxy.get("required_fields"), limit=24),
                "allowed_functions": _normalize_string_list(raw_proxy.get("allowed_functions"), limit=16),
                "proxy_quality": proxy_quality,
                "confidence": raw_proxy.get("confidence"),
                "approximation_loss": _normalize_text(str(raw_proxy.get("approximation_loss") or ""))[:520],
                "when_context": _normalize_text(str(raw_proxy.get("when_context") or ""))[:120],
                "context_match": bool(raw_proxy.get("context_match")),
            }
            validation_status, validation_reason = _validate_registry_proxy(proxy)
            proxy["validation_status"] = validation_status
            proxy["validation_reason"] = validation_reason
            local_proxies.append(proxy)
    local_proxies.sort(
        key=lambda item: (
            0 if item.get("validation_status") == "executable" else 1,
            0 if item.get("context_match") else 1,
            quality_rank.get(str(item.get("proxy_quality")), 1),
        )
    )
    best_proxy = local_proxies[0] if local_proxies else {}
    required_fields = _normalize_string_list(best_proxy.get("required_fields") or meta.get("required_fields"), limit=24)
    local_proxy = _normalize_text(str(best_proxy.get("expression") or meta.get("local_proxy") or ""))[:520]
    approximation_loss = _normalize_text(
        str(best_proxy.get("approximation_loss") or meta.get("approximation_loss") or "")
    )[:520]
    return {
        "paper_variable": raw_variable,
        "canonical_variable": canonical,
        "proxy_strength": strength,
        "local_proxy": local_proxy,
        "required_fields": required_fields,
        "approximation_loss": approximation_loss,
        "future_pipeline": _normalize_text(str(meta.get("future_pipeline") or ""))[:520],
        "local_proxies": local_proxies,
        "proxy_quality": best_proxy.get("proxy_quality", ""),
        "confidence": best_proxy.get("confidence", meta.get("confidence")),
        "validation_status": best_proxy.get("validation_status", ""),
        "validation_reason": best_proxy.get("validation_reason", ""),
        "when_context": best_proxy.get("when_context", ""),
        "review_status": _normalize_text(str(meta.get("review_status") or "unreviewed"))[:80],
        "reviewer": _normalize_text(str(meta.get("reviewer") or ""))[:80],
        "data_requirement": _normalize_text(str(meta.get("data_requirement") or ""))[:360],
        "role": _normalize_text(str(meta.get("role") or ""))[:80],
        "evidence_examples": _normalize_string_list(meta.get("evidence_examples"), limit=8),
    }


def _resolve_proxy_variable(raw_variable: object) -> Optional[Dict[str, object]]:
    text = _normalize_text(str(raw_variable or ""))
    if not text:
        return None
    variants = [text]
    head = re.split(r"\s*[\(（:：;；,，]\s*", text, maxsplit=1)[0].strip()
    if head and head != text:
        variants.append(head)
    variants.append(re.sub(r"\s+", "_", head or text))
    for variant in dict.fromkeys(v for v in variants if v):
        if variant in ALLOWED_FACTOR_FIELDS:
            return {
                "paper_variable": text,
                "canonical_variable": variant,
                "proxy_strength": "direct",
                "local_proxy": variant,
                "required_fields": [variant],
                "approximation_loss": "",
                "future_pipeline": "",
            }
    registry = _load_proxy_registry()
    exact_aliases = registry.get("exact_aliases", {})
    if isinstance(exact_aliases, dict):
        for variant in dict.fromkeys(v for v in variants if v):
            canonical = exact_aliases.get(_normalize_text(variant).lower())
            if canonical:
                return _proxy_mapping_from_registry(str(canonical), text)
    aliases = registry.get("aliases", {})
    if isinstance(aliases, dict):
        for variant in dict.fromkeys(v for v in variants if v):
            variant_key = _canonicalize_proxy_name(variant)
            canonical = aliases.get(variant_key)
            if canonical:
                return _proxy_mapping_from_registry(str(canonical), text)
            for alias_key, alias_canonical in sorted(aliases.items(), key=lambda item: len(str(item[0])), reverse=True):
                if len(str(alias_key)) < 5:
                    continue
                if variant_key.startswith(str(alias_key)):
                    return _proxy_mapping_from_registry(str(alias_canonical), text)
    return None


DEFAULT_PROMPT_PROXY_FAMILIES = {
    "return_series",
    "realized_volatility",
    "mid_price",
    "execution_friction",
    "volume_or_trade_activity",
    "order_book_imbalance",
    "lob_state_divergence",
}
PROMPT_REGISTRY_MAX_CHARS = 7200
PROMPT_REGISTRY_SUFFIX_MAX_CHARS = 420
PROMPT_MECHANISM_MAX_CHARS = 720


def _proxy_registry_prompt_line(canonical: str) -> str:
    registry = _load_proxy_registry()
    variables = registry.get("variables", {})
    mechanism_catalog = registry.get("mechanism_catalog", {})
    meta = variables.get(canonical, {}) if isinstance(variables, dict) else {}
    mechanism = mechanism_catalog.get(canonical, {}) if isinstance(mechanism_catalog, dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    if not isinstance(mechanism, dict):
        mechanism = {}
    mapping = _proxy_mapping_from_registry(canonical, canonical)
    strength = str(mapping.get("proxy_strength") or "unsupported")
    aliases = ",".join(_registry_aliases(meta.get("aliases"), include_suggested=False)[:6])
    local_proxy = _normalize_text(str(mapping.get("local_proxy") or ""))[:180]
    required_fields = ",".join(str(x) for x in mapping.get("required_fields", [])[:12])
    data_requirement = _normalize_text(str(mapping.get("data_requirement") or ""))[:180]
    loss = _normalize_text(str(mapping.get("approximation_loss") or mapping.get("future_pipeline") or ""))[:180]
    physics = _normalize_text(str(mechanism.get("physics_meaning") or ""))[:PROMPT_MECHANISM_MAX_CHARS]
    raw_interactions = mechanism.get("interaction_dimensions", [])
    interactions = ",".join(str(item) for item in raw_interactions[:6]) if isinstance(raw_interactions, list) else ""
    conceptual_expression = _normalize_text(str(mechanism.get("conceptual_expression") or ""))[:PROMPT_MECHANISM_MAX_CHARS]
    normalization = _normalize_text(str(mechanism.get("normalization_guidance") or ""))[:PROMPT_MECHANISM_MAX_CHARS]
    parts = [f"{canonical}: strength={strength}"]
    if aliases:
        parts.append(f"confirmed_aliases={aliases}")
    if local_proxy:
        parts.append(f"local_proxy={local_proxy}")
    if required_fields:
        parts.append(f"fields={required_fields}")
    if data_requirement:
        parts.append(f"data_requirement={data_requirement}")
    if loss:
        parts.append(f"loss={loss}")
    if physics:
        parts.append(f"physics={physics}")
    if interactions:
        parts.append(f"interactions={interactions}")
    if conceptual_expression:
        parts.append(f"conceptual_only={conceptual_expression}")
    if normalization:
        parts.append(f"normalization={normalization}")
    return "; ".join(parts)


def _proxy_registry_prompt_summary(limit: int = 40) -> str:
    registry = _load_proxy_registry()
    variables = registry.get("variables", {})
    if not isinstance(variables, dict) or not variables:
        return "本地代理变量知识库为空；factor_candidates仍必须遵守字段白名单和函数白名单。"
    reviewed_lines: List[str] = []
    needs_review: List[str] = []
    for canonical in sorted(str(key) for key in variables.keys()):
        meta = variables.get(canonical, {})
        if not isinstance(meta, dict):
            continue
        review_status = _normalize_text(str(meta.get("review_status") or "unreviewed"))
        if review_status != "reviewed":
            needs_review.append(canonical)
            continue
        reviewed_lines.append(_proxy_registry_prompt_line(canonical))
    header = (
        "本地代理变量知识库（仅reviewed条目可用于factor_candidates.proxy_mapping；"
        "paper_hf_factors仍保持论文忠实，不受本地字段限制）："
    )
    body = "\n".join(f"- {line}" for line in reviewed_lines[:limit])
    suffix = ""
    if needs_review:
        suffix = "\n需人工复核，LLM不得自动当作confirmed映射使用：" + ", ".join(needs_review[:20])
    return f"{header}\n{body}{suffix}"


def _append_prompt_line_with_budget(lines: List[str], line: str, max_chars: int) -> bool:
    if sum(len(item) + 1 for item in lines) + len(line) > max_chars:
        return False
    lines.append(line)
    return True


def _proxy_registry_prompt_context_for_article(title: str, summary: str, tags: List[str], limit: int = 18) -> str:
    registry = _load_proxy_registry()
    variables = registry.get("variables", {})
    aliases = registry.get("aliases", {})
    if not isinstance(variables, dict) or not isinstance(aliases, dict):
        return _proxy_registry_prompt_summary(limit=limit)
    compact_text = _canonicalize_proxy_name(" ".join([title, summary[:4000], " ".join(tags)]))
    selected = set(DEFAULT_PROMPT_PROXY_FAMILIES)
    hit_counts: Counter[str] = Counter()
    for alias_key, canonical in sorted(aliases.items(), key=lambda item: len(str(item[0])), reverse=True):
        if len(str(alias_key)) < 4:
            continue
        meta = variables.get(str(canonical), {})
        if not isinstance(meta, dict) or str(meta.get("review_status")) != "reviewed":
            continue
        if str(alias_key) in compact_text:
            selected.add(str(canonical))
            hit_counts[str(canonical)] += max(1, len(str(alias_key)))
    needs_review_hits: List[str] = []
    for canonical, meta in variables.items():
        if not isinstance(meta, dict) or str(meta.get("review_status")) == "reviewed":
            continue
        keys = [str(canonical), *_registry_aliases(meta.get("aliases"), include_suggested=False)]
        if any(_canonicalize_proxy_name(key) in compact_text for key in keys if len(_canonicalize_proxy_name(key)) >= 4):
            needs_review_hits.append(str(canonical))
    reviewed_selected = []
    for canonical in sorted(selected):
        meta = variables.get(canonical, {})
        if isinstance(meta, dict) and str(meta.get("review_status")) == "reviewed":
            reviewed_selected.append(canonical)
    reviewed_selected = sorted(
        reviewed_selected,
        key=lambda canonical: (canonical not in DEFAULT_PROMPT_PROXY_FAMILIES, -hit_counts.get(canonical, 0), canonical),
    )
    header = (
        "【系统强制约束：本篇文章相关高频变量代理解析表】\n"
        "以下是本篇可用的reviewed canonical变量。factor_candidates只能从这些canonical中选择；"
        "若论文变量不在表中，必须标为unsupported或future_pipeline，严禁自行发明derived映射。"
    )
    body_lines: List[str] = []
    for canonical in reviewed_selected[: max(limit * 2, limit)]:
        if len(body_lines) >= limit:
            break
        if not _append_prompt_line_with_budget(body_lines, f"- {_proxy_registry_prompt_line(canonical)}", PROMPT_REGISTRY_MAX_CHARS):
            break
    suffix = ""
    if needs_review_hits:
        suffix_text = ", ".join(needs_review_hits[:10])
        suffix = "\n本篇命中的needs_review变量，不得当作confirmed映射使用：" + suffix_text[:PROMPT_REGISTRY_SUFFIX_MAX_CHARS]
    return f"{header}\n" + "\n".join(body_lines) + suffix


def _collect_explicit_proxy_variables(item: Dict[str, object]) -> List[str]:
    raw_values: List[str] = []
    for key in ("paper_variables", "paper_variable", "variables", "ideal_input_fields"):
        value = item.get(key)
        if isinstance(value, list):
            raw_values.extend(str(x) for x in value if str(x).strip())
        elif value:
            raw_values.append(str(value))
    raw_mapping = item.get("proxy_mapping")
    if isinstance(raw_mapping, list):
        for entry in raw_mapping:
            if isinstance(entry, dict):
                canonical = entry.get("canonical_variable") or entry.get("canonical")
                if canonical:
                    raw_values.append(str(canonical))
                raw = entry.get("paper_variable") or entry.get("variable") or entry.get("name")
                if raw:
                    raw_values.append(str(raw))
            elif entry:
                raw_values.append(str(entry))
    elif isinstance(raw_mapping, dict):
        canonical = raw_mapping.get("canonical_variable") or raw_mapping.get("canonical")
        if canonical:
            raw_values.append(str(canonical))
        raw = raw_mapping.get("paper_variable") or raw_mapping.get("variable") or raw_mapping.get("name")
        if raw:
            raw_values.append(str(raw))
    return list(dict.fromkeys(_normalize_text(value) for value in raw_values if _normalize_text(value)))


def _resolve_candidate_proxy_mappings(item: Dict[str, object]) -> List[Dict[str, object]]:
    mappings: Dict[Tuple[str, str], Dict[str, object]] = {}
    explicit_variables = _collect_explicit_proxy_variables(item)
    for raw_variable in explicit_variables:
        resolved = _resolve_proxy_variable(raw_variable)
        if resolved and resolved.get("proxy_strength") != "direct":
            mappings[(str(resolved.get("canonical_variable")), str(resolved.get("paper_variable")))] = resolved

    if mappings:
        return sorted(
            mappings.values(),
            key=lambda x: (_proxy_strength_rank(str(x.get("proxy_strength", "unsupported"))), str(x.get("canonical_variable", ""))),
        )

    text_parts = []
    for key in (
        "source_factor",
        "paper_factor",
        "formula",
        "mechanism",
        "proxy_relation",
        "preserved_mechanism",
        "approximation_loss",
        "rationale",
    ):
        value = item.get(key)
        if value:
            text_parts.append(str(value))
    for key in ("calculation_steps",):
        value = item.get(key)
        if isinstance(value, list):
            text_parts.extend(str(x) for x in value if str(x).strip())
    compact_text = _canonicalize_proxy_name(" ".join(text_parts))
    if compact_text:
        registry = _load_proxy_registry()
        aliases = registry.get("aliases", {})
        if isinstance(aliases, dict):
            for alias_key, canonical in aliases.items():
                if len(alias_key) < 4:
                    continue
                if alias_key in compact_text:
                    resolved = _proxy_mapping_from_registry(str(canonical), str(canonical))
                    if resolved.get("proxy_strength") != "direct":
                        mappings[(str(resolved.get("canonical_variable")), str(resolved.get("paper_variable")))] = resolved
    return sorted(mappings.values(), key=lambda x: (_proxy_strength_rank(str(x.get("proxy_strength", "unsupported"))), str(x.get("canonical_variable", ""))))


def _candidate_proxy_summary(proxy_mappings: List[Dict[str, object]]) -> Tuple[str, List[str], str]:
    if not proxy_mappings:
        return ("direct", [], "")
    strongest = max((str(item.get("proxy_strength", "unsupported")) for item in proxy_mappings), key=_proxy_strength_rank)
    required_fields: List[str] = []
    losses: List[str] = []
    for item in proxy_mappings:
        required_fields.extend(str(x) for x in item.get("required_fields", []) if str(x).strip())
        loss = _normalize_text(str(item.get("approximation_loss") or item.get("future_pipeline") or ""))
        if loss:
            losses.append(loss)
    return (strongest, list(dict.fromkeys(required_fields)), "；".join(dict.fromkeys(losses))[:700])


def _normalize_loss_self_audit(raw: object) -> Dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    omitted = raw.get("omitted_core_variables", [])
    substituted = raw.get("substituted_variables", [])
    score_raw = raw.get("information_loss_score", raw.get("information_loss_percentage", 0))
    score = 0.0
    try:
        if isinstance(score_raw, str):
            score = float(score_raw.strip().rstrip("%"))
            if score > 1:
                score = score / 100.0
        else:
            score = float(score_raw or 0)
            if score > 1:
                score = score / 100.0
    except (TypeError, ValueError):
        score = 0.0
    return {
        "omitted_core_variables": _normalize_string_list(omitted, limit=16),
        "substituted_variables": _normalize_string_list(substituted, limit=16),
        "information_loss_score": round(max(0.0, min(1.0, score)), 4),
        "noise_source_introduced": _normalize_text(str(raw.get("noise_source_introduced") or ""))[:360],
        "is_volume_neglected": bool(raw.get("is_volume_neglected", False)),
    }


def _candidate_loss_reject_reason(
    *,
    expression: str,
    required_fields: List[str],
    proxy_mappings: List[Dict[str, object]],
    loss_self_audit: Dict[str, object],
    source_factor: str,
    mechanism: str,
    proxy_relation: str,
) -> str:
    if loss_self_audit:
        if loss_self_audit.get("is_volume_neglected"):
            return "loss_self_audit声明忽略了核心量能/成交量信息。"
        omitted = loss_self_audit.get("omitted_core_variables")
        if isinstance(omitted, list) and omitted:
            return "loss_self_audit声明遗漏核心变量：" + ", ".join(str(x) for x in omitted[:6])
        try:
            if float(loss_self_audit.get("information_loss_score") or 0) > 0.30:
                return "loss_self_audit信息损失超过30%。"
        except (TypeError, ValueError):
            pass
    context = _canonicalize_proxy_name(" ".join([source_factor, mechanism, proxy_relation]))
    wants_volume = any(key in context for key in ("volume", "turnover", "notional", "tradeflow", "orderflow", "liquidity", "cti"))
    has_volume_field = any(str(field) in {"volume", "money", "totalDeputeBuy", "totalDeputeSell"} for field in required_fields)
    has_volume_mapping = any(str(mapping.get("canonical_variable")) == "volume_or_trade_activity" for mapping in proxy_mappings)
    if wants_volume and not (has_volume_field or has_volume_mapping):
        return "论文机制涉及量能/成交/流动性，但候选表达式未使用本地量能字段或volume_or_trade_activity映射。"
    compact_expression = _canonicalize_proxy_name(expression)
    has_return_mapping = any(str(mapping.get("canonical_variable")) == "return_series" for mapping in proxy_mappings)
    if has_return_mapping and "pctchangeclose" in compact_expression and not any(field in required_fields for field in ("askP1", "bidP1", "last_close")):
        return "return_series存在更高质量mid-price代理，当前表达式退化为pct_change(close)。"
    return ""


def _collect_explicit_paper_factor_variables(factor: Dict[str, object]) -> List[str]:
    raw_values: List[str] = []
    for key in ("paper_variables", "variables", "ideal_input_fields"):
        value = factor.get(key)
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    raw = entry.get("variable") or entry.get("paper_variable") or entry.get("name")
                    if raw:
                        raw_values.append(str(raw))
                elif entry:
                    raw_values.append(str(entry))
        elif value:
            raw_values.append(str(value))
    return list(dict.fromkeys(_normalize_text(value) for value in raw_values if _normalize_text(value)))[:40]


def _collect_paper_factor_proxy_variables(factor: Dict[str, object]) -> List[str]:
    raw_values = _collect_explicit_paper_factor_variables(factor)
    text = " ".join(
        str(factor.get(key, ""))
        for key in ("mechanism_formula", "paper_mechanism", "meaning", "procedure", "rationale")
        if factor.get(key)
    )
    for token in EXPRESSION_FIELD_RE.findall(text):
        if token in ALLOWED_EXPRESSION_FUNCS or token in {"sum", "mean", "std", "min", "max", "where", "log", "exp"}:
            continue
        if len(token) <= 2 and token.lower() not in {"rv", "cti"}:
            continue
        raw_values.append(token)
    return list(dict.fromkeys(_normalize_text(value) for value in raw_values if _normalize_text(value)))[:40]


def _resolve_paper_factor_proxy_mappings(factor: Dict[str, object]) -> Tuple[List[Dict[str, object]], List[str]]:
    mappings: Dict[Tuple[str, str], Dict[str, object]] = {}
    unresolved: List[str] = []
    explicit_variables = set(_collect_explicit_paper_factor_variables(factor))
    for raw_variable in _collect_paper_factor_proxy_variables(factor):
        resolved = _resolve_proxy_variable(raw_variable)
        if resolved:
            mappings[(str(resolved.get("canonical_variable")), str(resolved.get("paper_variable")))] = resolved
        elif raw_variable in explicit_variables and raw_variable not in ALLOWED_FACTOR_FIELDS:
            compact = _canonicalize_proxy_name(raw_variable)
            if compact and compact not in {"signalt", "signal", "epsilon", "theta", "alpha", "beta", "gamma", "window", "where"}:
                unresolved.append(raw_variable)
    sorted_mappings = sorted(
        mappings.values(),
        key=lambda x: (_proxy_strength_rank(str(x.get("proxy_strength", "unsupported"))), str(x.get("canonical_variable", ""))),
    )
    compacted: Dict[str, Dict[str, object]] = {}
    for mapping in sorted_mappings:
        canonical = str(mapping.get("canonical_variable") or mapping.get("paper_variable") or "")
        if not canonical:
            continue
        previous = compacted.get(canonical)
        if previous is None or _proxy_strength_rank(str(mapping.get("proxy_strength", "unsupported"))) < _proxy_strength_rank(str(previous.get("proxy_strength", "unsupported"))):
            compacted[canonical] = mapping
    return list(compacted.values())[:12], list(dict.fromkeys(unresolved))[:12]


def _paper_factor_proxy_status(proxy_mappings: List[Dict[str, object]], unresolved: List[str]) -> Tuple[str, str]:
    strengths = {str(item.get("proxy_strength", "unsupported")) for item in proxy_mappings}
    if "unsupported" in strengths:
        return ("unsupported", "存在当前环境不可支持的核心或重要机制变量。")
    if "future_pipeline" in strengths:
        return ("future_pipeline_required", "部分机制变量需要新增数据、模型或外部管线。")
    if "weak_proxy" in strengths:
        return ("weak_proxy_available", "已识别部分弱代理变量，可尝试通过自定义公式执行。")
    if unresolved and not proxy_mappings:
        return ("unresolved", "未在知识库中识别到足够的论文变量，需要审计后归类。")
    if unresolved:
        return ("partially_computable", "部分变量可代理，但仍有未归类变量需要审计。")
    if proxy_mappings and all(str(item.get("proxy_strength")) in GENERATION_PROXY_STRENGTHS for item in proxy_mappings):
        return ("fully_computable", "已识别变量均可由本地字段直接或稳定派生。")
    return ("unresolved", "未识别到需注册表处理的论文变量。")


def attach_paper_factor_proxy_analysis(factors: List[Dict[str, object]]) -> List[Dict[str, object]]:
    analyzed: List[Dict[str, object]] = []
    for factor in factors:
        if not isinstance(factor, dict):
            continue
        item = dict(factor)
        proxy_mappings, unresolved_variables = _resolve_paper_factor_proxy_mappings(item)
        proxy_status, proxy_status_reason = _paper_factor_proxy_status(proxy_mappings, unresolved_variables)
        item["proxy_mappings"] = proxy_mappings
        item["proxy_status"] = proxy_status
        item["proxy_status_reason"] = proxy_status_reason
        item["unresolved_proxy_variables"] = unresolved_variables
        analyzed.append(item)
    return analyzed


def _summarize_llm_error(exc: Optional[Exception]) -> str:
    if exc is None:
        return "unknown error"
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"timeout after {exc.timeout} seconds"
    message = str(exc).replace("\n", " ").strip()
    if isinstance(exc, json.JSONDecodeError):
        return f"invalid JSON output: {message[:160]}"
    if "Command '['" in message and "timed out after" in message:
        match = re.search(r"timed out after ([0-9.]+) seconds", message)
        if match:
            return f"timeout after {match.group(1)} seconds"
    if message.startswith("LLM analysis failed via copilot: "):
        return message.removeprefix("LLM analysis failed via copilot: ")[:240]
    if "copilot exit code" in message:
        return message[:240]
    return f"{type(exc).__name__}: {message[:240]}"


def normalize_factor_candidates(raw_candidates: object) -> List[Dict[str, object]]:
    if not isinstance(raw_candidates, list):
        return []

    candidates: List[Dict[str, object]] = []
    for idx, item in enumerate(raw_candidates, start=1):
        if not isinstance(item, dict):
            continue

        template = _normalize_text(str(item.get("template") or "unsupported"))
        fallback_field = f"{template}_{idx}" if template in ALLOWED_FACTOR_TEMPLATES and template != "unsupported" else f"factor_{idx}"
        raw_name = _candidate_text(item.get("name"))
        raw_field = _candidate_text(item.get("field"))
        name = (raw_name or raw_field or fallback_field.replace("_", " "))[:120]
        field = _safe_factor_field(raw_field or fallback_field, fallback_field)
        expression = _normalize_text(str(item.get("expression") or ""))[:1400]
        required_fields = _normalize_string_list(item.get("required_fields"), limit=32)
        lookback = item.get("lookback") if item.get("lookback") is not None else None
        horizon = _normalize_text(str(item.get("horizon") or "ret60s"))
        direction = _normalize_text(str(item.get("direction") or "unknown"))
        rationale = _normalize_text(str(item.get("rationale") or ""))[:520]
        status = _normalize_text(str(item.get("status") or "candidate"))
        frequency = _normalize_text(str(item.get("frequency") or ""))[:80]
        formula = _normalize_text(str(item.get("formula") or expression or ""))[:700]
        calculation_steps = _normalize_string_list(item.get("calculation_steps"), limit=6)
        input_fields = _normalize_string_list(item.get("input_fields"), limit=32)
        mechanism = _normalize_text(str(item.get("mechanism") or ""))[:700]
        source_factor = _normalize_text(str(item.get("source_factor") or item.get("paper_factor") or ""))[:160]
        proxy_relation = _normalize_text(str(item.get("proxy_relation") or ""))[:700]
        preserved_mechanism = _normalize_text(str(item.get("preserved_mechanism") or ""))[:520]
        approximation_loss = _normalize_text(str(item.get("approximation_loss") or ""))[:520]
        loss_self_audit = _normalize_loss_self_audit(item.get("loss_self_audit"))
        proxy_mappings = _resolve_candidate_proxy_mappings(item)
        proxy_strength, proxy_required_fields, registry_approximation_loss = _candidate_proxy_summary(proxy_mappings)
        if registry_approximation_loss and not approximation_loss:
            approximation_loss = registry_approximation_loss[:520]

        if not name:
            continue
        if template not in ALLOWED_FACTOR_TEMPLATES:
            template = "unsupported"
            status = "unsupported_fields"
        if horizon not in ALLOWED_HORIZONS:
            horizon = "ret60s"
        if direction not in ALLOWED_DIRECTIONS:
            direction = "unknown"
        if status not in ALLOWED_FACTOR_STATUSES:
            status = "candidate"

        missing_fields = [x for x in required_fields if x not in ALLOWED_FACTOR_FIELDS]
        leaks_future_return = _has_future_return_reference(expression) or any(
            _has_future_return_reference(x) for x in required_fields
        )
        loss_reject_reason = _candidate_loss_reject_reason(
            expression=expression,
            required_fields=required_fields,
            proxy_mappings=proxy_mappings,
            loss_self_audit=loss_self_audit,
            source_factor=source_factor,
            mechanism=mechanism,
            proxy_relation=proxy_relation,
        )
        if missing_fields or leaks_future_return or template == "unsupported":
            template = "unsupported"
            status = "unsupported_fields"
            if leaks_future_return:
                expression = ""
                rationale = _normalize_text(f"{rationale} 表达式或字段包含未来收益标签，不能作为输入特征。")[:520]
            elif missing_fields and not rationale:
                rationale = f"当前字段白名单不包含：{', '.join(missing_fields[:6])}。"
        elif loss_reject_reason:
            template = "unsupported"
            status = "unsupported_fields"
            expression = ""
            rationale = _normalize_text(f"{rationale} {loss_reject_reason}")[:520]
        elif proxy_strength not in GENERATION_PROXY_STRENGTHS:
            template = "unsupported"
            status = "unsupported_fields"
            expression = ""
            variable_text = ", ".join(
                str(mapping.get("canonical_variable") or mapping.get("paper_variable"))
                for mapping in proxy_mappings[:6]
            )
            rationale = _normalize_text(
                f"{rationale} 论文核心变量需要{proxy_strength}代理（{variable_text}），第一版不自动生成可执行因子。"
            )[:520]
        elif mechanism_problem := _candidate_mechanism_support_problem(proxy_mappings, required_fields, expression):
            template = "unsupported"
            status = "unsupported_fields"
            expression = ""
            rationale = _normalize_text(f"{rationale} {mechanism_problem}")[:520]
        elif support_problem := _template_support_problem(template, required_fields):
            template = "unsupported"
            status = "unsupported_fields"
            rationale = _normalize_text(f"{rationale} {support_problem}")[:520]
        elif _is_low_information_candidate(template, required_fields, expression):
            template = "unsupported"
            status = "unsupported_fields"
            rationale = _normalize_text(
                f"{rationale} 纯一档买卖量差属于基准特征，信息量不足；请使用多档深度、滚动成交/金额或价格偏离类模板。"
            )[:520]

        candidates.append(
            {
                "field": field,
                "name": name,
                "expression": expression,
                "template": template,
                "required_fields": required_fields,
                "lookback": lookback,
                "horizon": horizon,
                "direction": direction,
                "rationale": rationale,
                "status": status,
                "frequency": frequency,
                "formula": formula,
                "calculation_steps": calculation_steps,
                "input_fields": input_fields,
                "proxy_mappings": proxy_mappings,
                "proxy_strength": proxy_strength,
                "proxy_required_fields": proxy_required_fields,
                "mechanism": mechanism,
                "source_factor": source_factor,
                "proxy_relation": proxy_relation,
                "preserved_mechanism": preserved_mechanism,
                "approximation_loss": approximation_loss,
                "loss_self_audit": loss_self_audit,
            }
        )
    return candidates[:FACTOR_CANDIDATE_LIMIT]


def _has_complete_analysis_fields(row: Dict[str, object], analysis_mode: str) -> bool:
    base_fields = {"core_idea", "hf_factor_points", "paper_hf_factors", "recommendation_score", "score_dimensions"}
    if not base_fields.issubset(row.keys()):
        return False
    dims = row.get("score_dimensions", {})
    if not isinstance(dims, dict):
        return False
    for key, _label in SCORE_DIMENSIONS:
        item = dims.get(key)
        if not isinstance(item, dict) or "score" not in item or "comment" not in item:
            return False
    current_agent = str(row.get("analysis_agent", ""))
    return analysis_mode != "llm" or (
        current_agent.startswith("paper-llm-agent:") and LLM_ANALYSIS_SCHEMA in current_agent
    )


def analyze_article(title: str, summary: str, tags: List[str]) -> Dict[str, object]:
    content = f"{title}. {summary}".strip()
    sentences = _split_sentences(content)
    core_idea = sentences[0] if sentences else title

    keyword_to_factor_point = {
        "microstructure": "可构造订单簿微观结构失衡因子（价量冲击/恢复速度）。",
        "order book": "可构造盘口深度不对称与挂撤单强度因子。",
        "tick": "可构造逐笔成交方向与短窗冲击衰减因子。",
        "intraday": "可构造日内时段分层稳定性因子（开盘/午后/尾盘）。",
        "market making": "可构造做市压力与价差弹性因子。",
        "transaction cost": "可构造成交成本敏感度与冲击成本因子。",
        "alpha": "可作为 alpha 组合中的补充信号并做去相关验证。",
        "hft": "可构造超短周期流动性状态切换因子。",
        "高频": "可构造高频成交密度与资金流向强度因子。",
        "因子": "可映射为可计算字段并纳入现有评估框架。",
    }

    lowered = content.lower()
    points: List[str] = []
    for kw, point in keyword_to_factor_point.items():
        if kw.lower() in lowered:
            points.append(point)
    if not points:
        points = [
            "可从文中变量关系提炼成短窗统计特征（rolling mean/std/corr）。",
            "可按不同股票池分层评估稳定性与可迁移性。",
        ]
    points = points[:3]

    lowered = content.lower()
    relevance = min(10, 5 + len(tags) + (2 if any(x in lowered for x in ["microstructure", "order book", "tick", "intraday", "market making", "transaction cost", "高频", "因子"]) else 0))
    statistical = 7 if any(x in lowered for x in ["outperform", "significantly", "state-of-the-art", "sharpe", "volatility smile", "empirical", "p<", "实证", "显著"]) else 5
    mechanism = 7 if any(x in lowered for x in ["mechanism", "microstructure", "decompose", "channel", "identity", "机制", "分解", "通道"]) else 5
    implementation = min(10, 5 + min(3, len(points)))
    cost_sensitivity = 6 if any(x in lowered for x in ["cost", "spread", "bid-ask", "liquidity", "transaction", "成本", "价差", "流动性"]) else 4
    generality = 7 if any(x in lowered for x in ["multiple", "across", "generality", "sectoral", "commodities", "equity", "fx", "多", "跨"]) else 5
    score_dimensions = {
        "relevance": {
            "label": "相关性",
            "score": relevance,
            "comment": "与高频因子构造的直接关联较强，能映射到可计算的交易/微结构特征。"
            if relevance >= 7
            else "与因子研究有一定关联，但需要额外转换才能映射到可交易信号。",
            "evidence": ", ".join(tags[:3]) if tags else "摘要关键词匹配",
            "critique": "需要确认文章问题是否真的能转化成可交易预测，而不只是解释性研究。",
        },
        "mechanism": {
            "label": "机制可信度",
            "score": mechanism,
            "comment": "摘要包含可解释的市场机制或统计分解，具备进一步落地为因子的基础。"
            if mechanism >= 7
            else "摘要未充分说明为什么该信号应在市场中持续存在。",
            "evidence": "摘要出现机制/分解/通道类关键词" if mechanism >= 7 else "摘要未披露清晰机制",
            "critique": "需要检查机制是否只是事后解释，是否能在样本外和交易成本后保留。",
        },
        "statistical": {
            "label": "统计可信度",
            "score": statistical,
            "comment": "摘要暗示有实证或显著性证据，但仍需正文确认样本切分、稳健性和多重检验。"
            if statistical >= 7
            else "摘要没有给出足够的绩效、显著性或稳健性数字。",
            "evidence": "摘要出现效果/实证/显著关键词" if statistical >= 7 else "摘要未披露明确绩效数字",
            "critique": "重点检查是否存在数据窥探、多重比较、样本选择和只报告正结果的问题。",
        },
        "implementation": {
            "label": "可实现性",
            "score": implementation,
            "comment": "可较直接落地为因子代码或实时特征工程，工程路径清晰。"
            if implementation >= 7
            else "思路可借鉴，但实现链路较长或依赖额外建模/数据。",
            "evidence": points[0] if points else "待 LLM 细化字段路径",
            "critique": "需要确认本地字段、延迟、窗口和线上计算状态是否足够支持该机制。",
        },
        "cost_sensitivity": {
            "label": "成本敏感性",
            "score": cost_sensitivity,
            "comment": "摘要涉及价差、流动性或交易成本，适合进一步做成本后评估。"
            if cost_sensitivity >= 6
            else "摘要没有充分讨论交易成本、冲击成本或容量约束。",
            "evidence": "摘要出现成本/价差/流动性关键词" if cost_sensitivity >= 6 else "摘要未披露成本设定",
            "critique": "高频因子若只在毛收益上显著，成本后可能完全消失。",
        },
        "generality": {
            "label": "普适性",
            "score": generality,
            "comment": "方法具备跨标的/跨频段迁移潜力，泛化空间较好。"
            if generality >= 7
            else "更偏向特定市场结构或特定问题设定，迁移性一般。",
            "evidence": "摘要出现跨样本/跨市场关键词" if generality >= 7 else "摘要未披露跨市场验证",
            "critique": "需要看跨市场、跨年份、不同波动 regime 下是否一致，而不是只在单一市场成立。",
        },
    }
    return {
        "core_idea": core_idea[:400],
        "structured_summary": _heuristic_structured_summary(title, summary, tags),
        "hf_factor_points": points,
        "paper_hf_factors": attach_paper_factor_proxy_analysis(normalize_paper_hf_factors(
            [
                {
                    "name": f"启发式高频因子 {idx}",
                    "frequency": "待 LLM 判断",
                    "mechanism_formula": "待 LLM 补机制公式",
                    "meaning": point,
                    "ideal_input_fields": [],
                    "paper_mechanism": point,
                    "source_evidence": tags[idx - 1] if idx - 1 < len(tags) else "关键词匹配",
                }
                for idx, point in enumerate(points, start=1)
            ]
        )),
        "score_dimensions": score_dimensions,
        "recommendation_score": _mean_recommendation_score(score_dimensions),
        "analysis_agent": "paper-heuristic-agent-v1",
    }


def _extract_json_block(text: str) -> Dict[str, object]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _is_rate_limit_error(exc: object) -> bool:
    text = str(exc).lower()
    return "429" in text or "too many request" in text or "rate limit" in text or "rate_limit" in text


class LLMCallLimitReached(RuntimeError):
    pass


class LLMRateLimitReached(RuntimeError):
    pass


def _reserve_llm_call(llm_config: Dict[str, object]) -> None:
    max_calls = int(llm_config.get("max_calls_per_run") or 0)
    calls_started = int(llm_config.get("calls_started") or 0)
    if max_calls > 0 and calls_started >= max_calls:
        raise LLMCallLimitReached(f"LLM call limit reached: {calls_started}/{max_calls}")
    llm_config["calls_started"] = calls_started + 1


def _mark_pending_llm(row: Dict[str, object], reason: str) -> Dict[str, object]:
    if not _has_complete_analysis_fields(row, "llm"):
        row.setdefault("core_idea", "")
        row.setdefault("structured_summary", {})
        row.setdefault("hf_factor_points", [])
        row.setdefault("paper_hf_factors", [])
        row.setdefault("factor_candidates", [])
        row.setdefault("score_dimensions", {})
        row.setdefault("recommendation_score", 0)
        row.setdefault("analysis_agent", "paper-pending-llm-v1")
    row["analysis_pending_llm"] = True
    row["analysis_error"] = reason
    return row


def _is_nonretryable_llm_output_error(reason: object) -> bool:
    text = str(reason).lower()
    if os.environ.get("PAPER_LLM_SKIP_PENDING_ERRORS", "1") == "1" and text:
        return True
    return any(
        marker in text
        for marker in (
            "missing structured_summary",
            "missing paper_hf_factors",
            "missing usable score_dimensions",
            "invalid json output",
        )
    )


def _validate_llm_analysis_payload(
    structured_summary: Dict[str, str],
    paper_hf_factors: List[Dict[str, object]],
    factor_candidates: List[Dict[str, object]],
    score_dimensions: Dict[str, Dict[str, object]],
) -> None:
    del factor_candidates
    if not structured_summary:
        raise RuntimeError("LLM output missing structured_summary")
    if not paper_hf_factors:
        raise RuntimeError("LLM output missing paper_hf_factors")
    if not score_dimensions or all(int(item.get("score", 0)) == 0 for item in score_dimensions.values()):
        raise RuntimeError("LLM output missing usable score_dimensions")


def llm_analyze_article(
    *,
    title: str,
    summary: str,
    tags: List[str],
    url: str,
    source_id: str,
    source_name: str,
    evidence_pack: Dict[str, object],
    model: str,
    timeout_sec: int,
    retries: int,
    retry_base_sec: float,
    retry_max_sec: float,
    retry_jitter_sec: float,
    min_interval_sec: float,
    copilot_bin: str,
) -> Dict[str, object]:
    prompt = (
        "你是严谨的量化研究员，专门从论文中抽取高频因子机制。只输出一个紧凑JSON对象，不要Markdown。"
        "目标质量：先像资深研究员做paper read一样批判性阅读，再生成因子；不要只复述标题或摘要。"
        "结构化摘要必须具体、详细、有判断：提炼问题、方法、数据、作者主张、局限、关键结果，并指出识别假设、统计稳健性、交易成本、样本外和可实现性风险。"
        "除field/template/expression/formula/required_fields/input_fields等代码或字段名外，所有自然语言说明必须使用中文。"
        "硬规则：paper_hf_factors是唯一主路径，只基于论文文本和金融/微结构机制生成。"
        "paper_hf_factors的ideal_input_fields必须由文章文本、公式、变量定义、实验对象或机制自然推导。"
        "如果文章未明确字段名，可写机制必需的抽象变量/统计量，并在字段名中体现来源，例如return_series,sign_residue_k2,magnitude_residue_k4,latent_regime,attention_weight,model_forecast。"
        "paper_hf_factors要比普通摘要更像因子设计：必须给展开后的机制公式或伪公式mechanism_formula、由文章机制推导出的ideal_input_fields、变量角色、含义、论文机制、新鲜性和经典基线。"
        "每个paper_hf_factor还必须给paper_hf_formula_plan，用结构化字段说明如何映射到本地代理生成模板；只能引用config/proxy_variant_templates.yaml中声明的template/operator，不允许输出任意Python表达式。"
        "paper_hf_formula_plan含template_id,operator_family,inputs,windows,normalization,direction,rationale,fallback_template；template_id/fallback_template应优先从paper_hf_lob_vector_zdistance,paper_hf_micro_noise_trace,paper_hf_signed_flow_pressure,paper_hf_notional_imbalance,paper_hf_obi_return_pressure,paper_hf_volume_weighted_return,paper_hf_vol_scaled_return,paper_hf_spread_adjusted_return,paper_hf_order_book_imbalance,paper_hf_activity_surge,paper_hf_rolling_corr_return_obi,paper_hf_cost_adjusted_score,paper_hf_no_trade_band_distance中选。"
        "如果论文机制包含矩阵/协方差/积分/期望/优化解，只在operator_family中写matrix_covariance,rolling_integral,conditional_expectation,cost_adjusted_optimization,no_trade_band等抽象算子族，并选择最接近的template_id或fallback_template；不要发明未声明模板。"
        "mechanism_type必须用稳定短标签，例如lob_vector_divergence,microstructure_noise_covariance,volume_weighted_momentum,obi_conditioned_momentum,spread_adjusted_residual,vol_scaled_return,latent_state,attention_masked_signal,portfolio_policy,other。"
        "variable_roles逐项说明变量在机制中的角色，例如price_state,volume_weight,conditioning_signal,normalizer,latent_state,model_output,shock_measure。"
        "novelty_reason说明相对经典momentum/OBI/spread/volatility/volume因子的新机制；classic_baseline写最接近的经典基线。"
        "unobservable_variables列出本地无法直接观测但论文机制需要的变量；minimum_data_needed列出忠实复现该paper_hf_factor所需的最小数据。"
        "mechanism_formula优先写成直观完整定义，必要时同时给等价短式；例如signal_t=-(|r_{t-1}|-mu_w(|r|))/(sigma_w(|r|)+eps) ≈ -zscore(|r_{t-1}|;w)，BounceRate=(1/N)sum I[bid-side after ask-side]+I[ask-side after bid-side]。不要只写zscore/mean等黑箱短名。"
        "输出schema_version='v6'。structured_summary含problem,method,data,author_claim,limitations,critical_assessment,missing_tests,key_results。"
        "structured_summary每项2-4句，尽量包含数字、公式、样本、结论、反例或风险；如果摘要没有披露，必须写清'摘要未披露'并说明为什么这会影响可信度。"
        "critical_assessment必须批判这篇文章：至少覆盖识别假设是否充分、统计检验是否可能过拟合/多重检验、结论是否可能只是解释性而非预测性、交易成本或线上执行是否会削弱结论。"
        "missing_tests列出还需要作者或我们补做的验证，例如样本外、滚动窗口、分层regime、成本后收益、容量、字段可实现性、消融或反事实检验。"
        "score_dimensions的relevance/mechanism/statistical/implementation/cost_sensitivity/generality各含score,comment,evidence,critique；evidence是原文短证据短语或数字，critique必须写扣分原因或需要警惕的问题。"
        "输入包含article_meta、evidence_pack_v2、context_providers；必须优先使用evidence_pack_v2，把它视为研究员整理的paper reading note，而不是论文全文。"
        "evidence_pack_v2中section_map给去噪章节图，intro_claims给问题/机制/贡献/数据主张，formula_evidence把公式、附近解释和变量绑定，variable_definitions给变量定义，method_evidence/data_sample_evidence/empirical_results分别给方法、样本与结果证据，experimental_formula_evidence/code_evidence/conclusion_evidence分别给实验公式、代码/算法和结论/限制证据，missing_evidence显式列出输入未披露项。"
        "旧版evidence_pack只作为回退：section_overview是去掉参考文献/附录后的章节地图，intro_context是Introduction开头语境，formula_contexts是公式块及其前后解释行，method_blocks和empirical_setup_snippets是方法/实证设置片段，conclusion_context/code_or_algorithm_snippets/experimental_formula_contexts是在下载构包阶段抽取的结论、代码和实验公式证据，quality_checks标记抽取可信度。"
        "不得使用结论/Discussion/未来工作作为因子证据；所有关键结果、公式、变量、统计评价和评分证据必须优先来自abstract/evidence_pack_v2/evidence_pack。若missing_evidence写'输入未披露'，输出不得补造对应样本、t值、Sharpe、IC、交易成本、样本外、容量或字段可得性。"
        "所有paper_hf_factors.source_evidence和score_dimensions.evidence必须尽量引用evidence_pack_v2中的短证据或source anchor；若只能从机制推导，必须明确写'由机制推导，输入未直接给出因子'。"
        "输入可能包含context_providers.mechanism_taxonomy_context：这是从外部机制分类表检索出的少量相关类别；每个paper_hf_factor必须在mechanism_category中填其中一个id，若完全不适用才填other，并按该类别的standard_operator做proxy映射。"
        f"paper_hf_factors给3-{PAPER_HF_FACTOR_LIMIT}个，每项含name,frequency,mechanism_category,mechanism_type,mechanism_formula,paper_hf_formula_plan,meaning,ideal_input_fields,variable_roles,paper_mechanism,source_evidence,novelty_reason,classic_baseline,unobservable_variables,minimum_data_needed；必须尽量贴合论文的核心机制。"
        "如果文章没有直接给出合适的高频因子，也必须基于文章核心机制主动构造一个合理的paper_hf_factor，并在source_evidence或paper_mechanism中明确说明这是由机制推导而非作者直接给出的因子。"
        "还需core_idea(一句话机制摘要，必须包含核心机制和最大风险),hf_factor_points(2-3条，概括论文高频启发，不要写成本地可计算代理),recommendation_score。"
        "若摘要信息不足，明确写'摘要未披露'，不要编造样本区间、Sharpe或IC。"
    )
    mechanism_taxonomy_context = _mechanism_taxonomy_context(
        title=title,
        summary=summary,
        tags=tags,
        evidence_pack=evidence_pack,
    )
    user_payload = {
        "article_meta": {
            "title": title,
            "url": url,
            "source_id": source_id,
            "source_name": source_name,
            "tags": tags,
        },
        "abstract": summary[:3000],
        "evidence_pack_v2": build_evidence_pack_v2(evidence_pack),
        "evidence_pack": evidence_pack,
        "context_providers": {
            "mechanism_taxonomy_context": mechanism_taxonomy_context,
            "proxy_template_context": "Use only declared template_id/operator families listed in the system instructions and config/proxy_variant_templates.yaml.",
            "local_capability_context": {
                "available_local_fields": sorted(ALLOWED_FACTOR_FIELDS),
                "allowed_horizons": sorted(ALLOWED_HORIZONS),
            },
        },
    }
    llm_prompt = (
        f"{prompt}\n"
        f"模型标记: {model}\n"
        "输入如下（JSON）：\n"
        f"{json.dumps(user_payload, ensure_ascii=False)}\n"
        "请仅输出JSON。"
    )
    last_err: Optional[Exception] = None

    def _retry_wait(attempt_idx: int) -> float:
        exp = retry_base_sec * (2 ** attempt_idx)
        return max(0.1, min(retry_max_sec, exp + retry_jitter_sec))

    for i in range(max(1, retries)):
        try:
            global _LAST_LLM_REQUEST_TS
            if min_interval_sec > 0:
                now_ts = time.time()
                wait_sec = min_interval_sec - (now_ts - _LAST_LLM_REQUEST_TS)
                if wait_sec > 0:
                    time.sleep(wait_sec)
            _LAST_LLM_REQUEST_TS = time.time()
            proc = subprocess.run(
                [copilot_bin, "--model", model, "-s", "-p", llm_prompt],
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1, timeout_sec),
                check=False,
            )
            if proc.returncode != 0:
                stderr = (proc.stderr or "").strip()[:400]
                raise RuntimeError(f"copilot exit code {proc.returncode}: {stderr}")
            content = (proc.stdout or "").strip()
            if not content:
                raise RuntimeError("copilot returned empty output")
            parsed = _extract_json_block(content)
            structured_summary = _normalize_structured_summary(parsed.get("structured_summary", {}))
            points = parsed.get("hf_factor_points", [])
            paper_hf_factors = attach_paper_factor_proxy_analysis(normalize_paper_hf_factors(parsed.get("paper_hf_factors", [])))
            score_dimensions = _normalize_dimension_scores(parsed.get("score_dimensions", {}))
            score = _mean_recommendation_score(score_dimensions)
            factor_candidates: List[Dict[str, object]] = []
            _validate_llm_analysis_payload(structured_summary, paper_hf_factors, factor_candidates, score_dimensions)
            return {
                "core_idea": str(parsed.get("core_idea", ""))[:400],
                "structured_summary": structured_summary,
                "hf_factor_points": [str(x)[:200] for x in points][:4],
                "paper_hf_factors": paper_hf_factors,
                "factor_candidates": factor_candidates,
                "score_dimensions": score_dimensions,
                "recommendation_score": score,
                "analysis_agent": f"paper-llm-agent:{model}:{LLM_ANALYSIS_SCHEMA}",
                "analysis_pending_llm": False,
            }
        except (KeyError, ValueError, TypeError, subprocess.SubprocessError) as exc:
            last_err = exc
            if i < retries - 1:
                time.sleep(_retry_wait(i))
        except RuntimeError as exc:
            last_err = exc
            if _is_rate_limit_error(exc):
                raise LLMRateLimitReached(str(exc))
            if i < retries - 1:
                time.sleep(_retry_wait(i))
    raise RuntimeError(f"LLM analysis failed: {_summarize_llm_error(last_err)}")


def ensure_analysis_fields(
    row: Dict[str, object],
    *,
    analysis_mode: str,
    llm_config: Dict[str, object],
    errors: List[str],
) -> Dict[str, object]:
    refresh_llm = analysis_mode == "llm" and bool(llm_config.get("refresh", False))
    if _has_complete_analysis_fields(row, analysis_mode) and not refresh_llm:
        return row
    if analysis_mode == "llm" and row.get("analysis_error") and os.environ.get("PAPER_LLM_SKIP_BAD_OUTPUT", "1") == "1":
        return row
    title = str(row.get("title", ""))
    summary = str(row.get("summary", ""))
    tags = [str(x) for x in row.get("tags", [])]
    if analysis_mode == "llm":
        try:
            _reserve_llm_call(llm_config)
            evidence_pack = build_arxiv_evidence_pack(
                row,
                timeout_sec=int(llm_config.get("evidence_timeout_sec", ARXIV_EVIDENCE_TIMEOUT_SEC)),
                user_agent=str(llm_config.get("user_agent", "factor-study-paper-bot/1.0")),
            )
            if evidence_pack:
                row["llm_input_evidence_pack"] = evidence_pack
            analysis = llm_analyze_article(
                title=title,
                summary=summary,
                tags=tags,
                url=str(row.get("url", "")),
                source_id=str(row.get("source_id", "")),
                source_name=str(row.get("source_name", "")),
                evidence_pack=evidence_pack,
                model=str(llm_config["model"]),
                timeout_sec=int(llm_config["timeout_sec"]),
                retries=int(llm_config["retries"]),
                retry_base_sec=float(llm_config["retry_base_sec"]),
                retry_max_sec=float(llm_config["retry_max_sec"]),
                retry_jitter_sec=float(llm_config["retry_jitter_sec"]),
                min_interval_sec=float(llm_config["min_interval_sec"]),
                copilot_bin=str(llm_config["copilot_bin"]),
            )
        except (LLMCallLimitReached, LLMRateLimitReached):
            raise
        except Exception as exc:
            if bool(llm_config["fallback_heuristic"]):
                analysis = analyze_article(title=title, summary=summary, tags=tags)
                analysis["analysis_agent"] = "paper-heuristic-fallback-v1"
                analysis["analysis_pending_llm"] = True
                row["analysis_error"] = _summarize_llm_error(exc)
                errors.append(f"analysis:{title[:50]}: {_summarize_llm_error(exc)}")
            else:
                row["analysis_pending_llm"] = True
                row["analysis_error"] = _summarize_llm_error(exc)
                errors.append(f"analysis-pending:{title[:50]}: {_summarize_llm_error(exc)}")
                return row
    else:
        analysis = analyze_article(title=title, summary=summary, tags=tags)
        analysis["analysis_pending_llm"] = False
    row.update(analysis)
    if str(row.get("analysis_agent", "")).startswith("paper-llm-agent:"):
        row.pop("analysis_error", None)
        row["analysis_pending_llm"] = False
    return row


def _analysis_cache_key(row: Dict[str, object]) -> str:
    dedup_key = str(row.get("dedup_key", "")).strip()
    if dedup_key:
        return dedup_key
    title = _normalize_text(str(row.get("title", ""))).lower()
    source = _normalize_text(str(row.get("source_id", ""))).lower()
    return f"{source}|{title}"


def analyze_rows_with_cache(
    rows: List[Dict[str, object]],
    *,
    analysis_mode: str,
    llm_config: Dict[str, object],
    errors: List[str],
    cache: Dict[str, Dict[str, object]],
) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    for row_index, row in enumerate(rows):
        key = _analysis_cache_key(row)
        cached = cache.get(key)
        cached_agent = str(cached.get("analysis_agent", "")) if cached is not None else ""
        cached_error = str(cached.get("analysis_error", "")) if cached is not None else ""
        skip_bad_llm_output = os.environ.get("PAPER_LLM_SKIP_BAD_OUTPUT", "1") == "1"
        if cached is not None and (
            analysis_mode != "llm"
            or LLM_ANALYSIS_SCHEMA in cached_agent
            or (cached.get("analysis_error") and os.environ.get("PAPER_LLM_SKIP_BAD_OUTPUT", "1") == "1")
            or (skip_bad_llm_output and bool(cached.get("analysis_pending_llm")) and _is_nonretryable_llm_output_error(cached_error))
        ):
            row.update(cached)
            out.append(row)
            continue
        try:
            updated = ensure_analysis_fields(
                row,
                analysis_mode=analysis_mode,
                llm_config=llm_config,
                errors=errors,
            )
        except (LLMCallLimitReached, LLMRateLimitReached) as exc:
            reason = _summarize_llm_error(exc)
            errors.append(f"analysis-limit:{reason}")
            out.append(_mark_pending_llm(row, reason))
            for remaining in rows[row_index + 1 :]:
                out.append(_mark_pending_llm(remaining, reason))
            break
        cache_entry: Dict[str, object] = {
            "core_idea": updated.get("core_idea", ""),
            "structured_summary": _normalize_structured_summary(updated.get("structured_summary", {})),
            "hf_factor_points": list(updated.get("hf_factor_points", [])),
            "paper_hf_factors": attach_paper_factor_proxy_analysis(normalize_paper_hf_factors(updated.get("paper_hf_factors", []))),
            "factor_candidates": normalize_factor_candidates(updated.get("factor_candidates", [])),
            "score_dimensions": json.loads(json.dumps(updated.get("score_dimensions", {}), ensure_ascii=False)),
            "recommendation_score": float(updated.get("recommendation_score", 0)),
            "analysis_agent": updated.get("analysis_agent", ""),
            "analysis_pending_llm": bool(updated.get("analysis_pending_llm", False)),
        }
        if "analysis_error" in updated:
            cache_entry["analysis_error"] = updated.get("analysis_error", "")
        cache[key] = cache_entry
        out.append(updated)
    return out


def _base_style() -> str:
    return """
body{font-family:Inter,Arial,sans-serif;background:#0b1020;color:#e8ecf1;margin:0}
.wrap{max-width:1200px;margin:0 auto;padding:24px}
.hero{padding:18px 20px;border-radius:14px;background:linear-gradient(135deg,#1d2b64,#4b6cb7)}
.hero h1{margin:0 0 8px 0;font-size:28px}
.muted{color:#c7d1e0}
.grid{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-top:16px}
.panel{background:#131a2d;border:1px solid #26314d;border-radius:12px;padding:14px}
.card{background:#0f1528;border:1px solid #2a3552;border-radius:10px;padding:12px;margin:10px 0}
.dashboard{margin-top:16px;background:#131a2d;border:1px solid #26314d;border-radius:12px;padding:14px}
.dashboard-head{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:12px}
.dashboard-head h2{margin:0;color:#f4f8ff;font-size:18px}
.dashboard-note{color:#9eb0c9;font-size:12px;line-height:1.45;max-width:760px}
.stat-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:10px 0}
.stat-card{background:#0f1528;border:1px solid #2a3552;border-radius:8px;padding:10px;min-height:64px}
.stat-label{color:#9eb0c9;font-size:12px;margin-bottom:5px}
.stat-value{color:#f4f8ff;font-size:24px;font-weight:800;line-height:1.1}
.stat-sub{color:#c7d1e0;font-size:11px;margin-top:5px;line-height:1.35}
.threshold-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:10px}
.threshold-card{background:#111a30;border:1px solid #253250;border-radius:8px;padding:8px}
.threshold-card strong{display:block;color:#9fc5ff;font-size:12px;margin-bottom:4px}
.threshold-card span{display:block;color:#f4f8ff;font-size:16px;font-weight:800}
.ic-interval-card{cursor:pointer;text-align:left;color:inherit}
.ic-interval-card.active{border-color:#35a969;background:#173a2b}
.ic-interval-card em{display:block;color:#9eb0c9;font-size:11px;font-style:normal;margin-top:2px}
.paper-search{margin-top:13px;background:#0f1528;border:1px solid #2a3552;border-radius:10px;padding:11px}
.paper-search-title{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:9px;color:#f4f8ff;font-size:18px;font-weight:800}
.paper-search-title span{color:#9eb0c9;font-size:12px;font-weight:600}
.search-row{display:grid;grid-template-columns:auto 1fr;gap:8px;align-items:center}
.search-icon{display:grid;place-items:center;width:38px;height:38px;border:1px solid #2a3552;border-radius:8px;background:#111a30;color:#9fc5ff;font-size:18px}
.search-row input{width:100%;box-sizing:border-box;background:#111a30;border:1px solid #2a3552;border-radius:8px;color:#e8ecf1;padding:10px 12px;font-size:14px}
.search-row input::placeholder{color:#7f8da8}
.search-tabs{display:flex;flex-wrap:wrap;gap:8px;margin-top:9px}
.search-tab{background:#111a30;border:1px solid #2a3552;border-radius:999px;color:#c8d6eb;padding:6px 12px;font-size:12px;font-weight:800;cursor:pointer}
.search-tab.active{background:#1d3a2f;border-color:#276b48;color:#8ef0b7}
.controls{display:grid;grid-template-columns:repeat(2,minmax(140px,1fr));gap:10px;margin-top:10px}
.controls select{width:100%;box-sizing:border-box;background:#0f1528;border:1px solid #2a3552;border-radius:8px;color:#e8ecf1;padding:9px 10px;font-size:13px}
.result-count{margin-top:9px;color:#9eb0c9;font-size:12px}
.card h3{margin:0 0 6px 0;font-size:18px}
a{color:#80b3ff;text-decoration:none}
a:hover{text-decoration:underline}
.meta{font-size:12px;color:#9eb0c9;margin-bottom:6px}
.score{display:inline-block;padding:2px 8px;border-radius:999px;background:#1d3a2f;color:#8ef0b7;font-weight:700}
.score-proxy{margin-left:6px;background:#173a2b;color:#9ff6c4;border:1px solid #35a969}
.score-muted{margin-left:6px;background:#26314d;color:#c7d1e0;border:1px solid #3a496b}
.read-section{margin-top:12px}
.read-section-title{margin:0 0 8px 0;color:#f4f8ff;font-size:14px;font-weight:800}
.dim-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:10px}
.dim-card{background:#111a30;border:1px solid #253250;border-radius:8px;padding:8px}
.dim-head{display:flex;justify-content:space-between;gap:8px;font-size:13px;font-weight:700}
.dim-desc{margin-top:4px;color:#c8d3e3;font-size:12px;line-height:1.45}
.dim-evidence{margin-top:6px;color:#9eb0c9;font-size:11px;line-height:1.4}
.structured-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:10px 0}
.summary-block{background:#111a30;border:1px solid #253250;border-radius:8px;padding:9px}
.summary-block.key_results,.summary-block.critical_assessment,.summary-block.missing_tests{grid-column:1/-1}
.summary-label{font-size:12px;font-weight:800;color:#9fc5ff;margin-bottom:4px}
.summary-text{font-size:12px;line-height:1.55;color:#d5deec}
.llm-section{margin-top:12px;background:#0f1528;border:1px solid #2a3552;border-radius:10px;padding:11px}
.section-title{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px;color:#f4f8ff;font-size:14px;font-weight:800}
.section-title span{color:#9eb0c9;font-size:11px;font-weight:600}
.llm-section p{margin:8px 0;color:#d8e1ef;line-height:1.55}
.llm-section ul{margin-top:6px}
.factor-values-section{margin-top:12px;background:#0f1528;border:1px solid #2a3552;border-radius:10px;padding:11px}
.factor-value-list{display:grid;grid-template-columns:1fr;gap:8px;margin-top:8px}
.factor-value-card{background:#111a30;border:1px solid #253250;border-radius:8px;padding:9px}
.factor-value-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;font-size:13px;font-weight:800;color:#f4f8ff}
.factor-value-head code{color:#9fc5ff;background:#0f1528;border:1px solid #2a3552;border-radius:5px;padding:1px 5px;font-size:12px}
.factor-value-badge{flex:0 0 auto;border-radius:999px;padding:3px 8px;font-size:11px;font-weight:800;border:1px solid transparent}
.factor-value-badge.ok{background:#143624;color:#8ef0b7;border-color:#276b48}
.factor-value-badge.warn{background:#26314d;color:#c7d1e0;border-color:#3a496b}
.factor-value-badge.bad{background:#3a2430;color:#f0a7ba;border-color:#7d3a4c}
.factor-value-badge.quality-strong{background:#173a2b;color:#9ff6c4;border-color:#35a969}
.factor-value-badge.quality-good{background:#183722;color:#9be7a8;border-color:#357c47}
.factor-value-badge.quality-negative{background:#362448;color:#dfb2ff;border-color:#7447a3}
.factor-value-badge.quality-watch{background:#3a3219;color:#f4d47a;border-color:#806629}
.factor-value-badge.quality-weak{background:#3a2430;color:#f0a7ba;border-color:#7d3a4c}
.factor-quality-row{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.factor-quality-badge{display:inline-flex;align-items:center;border-radius:999px;padding:3px 8px;font-size:11px;font-weight:800;border:1px solid #3a496b;background:#131a2d;color:#c7d1e0}
.factor-quality-badge.good{background:#143624;color:#8ef0b7;border-color:#276b48}
.factor-quality-badge.bad{background:#332236;color:#f0a6d2;border-color:#6b3a5d}
.factor-quality-badge.neutral{background:#26314d;color:#c7d1e0;border-color:#3a496b}
.factor-quality-badge.positive{background:#122d43;color:#8bd3ff;border-color:#25658e}
.factor-quality-badge.negative{background:#35271c;color:#ffd08a;border-color:#72552e}
.factor-value-expression{margin-top:6px;color:#aebdd2;font-family:Consolas,"SFMono-Regular",monospace;font-size:11px;line-height:1.45;overflow-wrap:anywhere}
.factor-value-detail{margin-top:7px;background:#0f1528;border:1px solid #2a3552;border-radius:8px;padding:8px;color:#d4deec;font-size:12px;line-height:1.55}
.factor-value-detail strong{display:block;color:#9fc5ff;margin-bottom:3px;font-size:11px;letter-spacing:.02em}
.factor-value-detail ul{margin:4px 0 0 16px}
.factor-value-metrics{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.factor-value-metric{background:#0f1528;border:1px solid #2a3552;border-radius:999px;padding:3px 8px;color:#dce8ff;font-size:12px}
.factor-value-metric strong{color:#9fc5ff}
.factor-value-unavailable{margin-top:8px;background:#131a2d;border:1px solid #26314d;border-radius:8px;padding:7px 9px;color:#c7d1e0;font-size:12px;line-height:1.5}
.factor-list{display:grid;grid-template-columns:1fr;gap:10px;margin:8px 0 12px 0}
.factor-card{background:#111a30;border:1px solid #253250;border-radius:8px;padding:10px}
.factor-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;font-size:13px;font-weight:700}
.factor-name{color:#f4f8ff;font-size:14px;line-height:1.35}
.factor-name code{color:#9fc5ff;background:#0f1528;border:1px solid #2a3552;border-radius:5px;padding:1px 5px;font-size:12px}
.factor-status{flex:0 0 auto;border-radius:999px;padding:3px 9px;font-size:11px;font-weight:700;border:1px solid transparent}
.factor-status.ok{background:#143624;color:#8ef0b7;border-color:#276b48}
.factor-status.warn{background:#26314d;color:#c7d1e0;border-color:#3a496b}
.factor-meta{margin-top:8px;display:flex;flex-wrap:wrap;gap:6px;color:#9eb0c9;font-size:12px;line-height:1.45}
.factor-chip{display:inline-flex;align-items:center;gap:4px;background:#0f1528;border:1px solid #2a3552;border-radius:999px;padding:3px 8px;color:#c8d6eb}
.factor-chip strong{color:#edf3ff;font-weight:700}
.factor-expression{margin-top:10px;background:#0f1528;border:1px solid #2a3552;border-radius:8px;color:#dce8ff;overflow:hidden}
.factor-expression-label{display:flex;justify-content:space-between;gap:8px;background:#131a2d;border-bottom:1px solid #26314d;padding:7px 10px;color:#9fc5ff;font-size:11px;font-weight:700;letter-spacing:.02em;text-transform:uppercase}
.factor-expression-label span:last-child{color:#d7e6ff;text-transform:none;letter-spacing:0}
.factor-formula{display:block;padding:11px 12px;font-family:Consolas,"SFMono-Regular",monospace;font-size:12px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere}
.factor-formula .fn{color:#8ef0b7}
.factor-formula .field{color:#9fc5ff}
.factor-formula .num{color:#c7d1e0}
.factor-formula .op{color:#80b3ff;padding:0 1px}
.factor-formula .paren{color:#c8d3e3}
.factor-rationale{margin-top:8px;color:#c8d3e3;font-size:12px;line-height:1.55;background:#0f1528;border-left:3px solid #80b3ff;padding:7px 9px;border-radius:6px}
.factor-detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
.factor-detail{background:#0f1528;border:1px solid #2a3552;border-radius:8px;padding:8px;color:#cdd8e8;font-size:12px;line-height:1.5;overflow:auto}
.factor-detail strong{display:block;color:#edf3ff;margin-bottom:6px;font-size:12px;text-transform:uppercase;letter-spacing:.02em}
.factor-detail ul{margin:4px 0 0 16px}
.factor-detail table{width:100%;border-collapse:collapse;font-size:11.5px;line-height:1.35;min-width:520px}
.factor-detail th,.factor-detail td{border-bottom:1px solid #26314d;padding:6px 7px;text-align:left;vertical-align:top;white-space:nowrap}
.factor-detail th{position:sticky;top:0;background:#151f35;color:#9fc5ff;font-size:11px;font-weight:800;z-index:1}
.factor-detail td{color:#d5deec}
.factor-detail td code{display:inline-block;max-width:360px;overflow:hidden;text-overflow:ellipsis;vertical-align:bottom;color:#b9d4ff;background:#101a2e;border:1px solid #26314d;border-radius:5px;padding:1px 5px;font-size:11px}
.utility-grid{grid-template-columns:1fr;gap:10px}
.utility-grid .factor-detail{padding:10px;background:#0d1628}
.utility-grid .factor-detail table{min-width:1320px;font-size:12px}
.utility-grid .factor-detail th{font-size:11.5px}
.utility-grid .factor-detail td code{max-width:480px}
.paper-hf-variant{margin-top:10px;background:#0d1425;border:1px solid #31405f;border-radius:8px;padding:10px;color:#dbe7f7;font-size:12px;line-height:1.55}
.paper-hf-variant-title{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-bottom:8px;color:#f2f6ff;font-weight:700}
.paper-hf-variant-section{margin-top:8px;padding-top:8px;border-top:1px solid #26344f}
.paper-hf-variant-section strong{display:block;color:#a9c8ff;margin-bottom:4px;font-size:11px;letter-spacing:.02em}
.paper-hf-row-details{margin-top:8px}
.paper-hf-row-details summary{cursor:pointer;color:#cfe0ff;font-weight:700}
.factor-eval{margin-top:9px;background:#0f1528;border:1px solid #2a3552;border-radius:8px;padding:8px 9px;color:#d9e6f8;font-size:12px;line-height:1.55}
.factor-eval.unavailable{background:#131a2d;border-color:#26314d;color:#c7d1e0}
.factor-eval strong{color:#edf3ff}
.tags{font-size:12px;color:#9fc5ff}
ul{margin:8px 0 0 18px}
li{margin:4px 0}
@media (max-width: 980px){.grid{grid-template-columns:1fr}.stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.threshold-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.controls{grid-template-columns:1fr}.dim-grid{grid-template-columns:1fr}.structured-summary{grid-template-columns:1fr}.factor-detail-grid{grid-template-columns:1fr}}
"""


def _format_metric(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    if not (numeric == numeric):
        return "-"
    return f"{numeric:.4f}"


def _format_ratio(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    if not (numeric == numeric):
        return "-"
    return f"{numeric * 100:.1f}%"


def _format_int_metric(value: object) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "-"


def _paper_hf_proxy_quality_label(metrics: Dict[str, object], tier: str = "small") -> Dict[str, str]:
    return paper_hf_proxy_quality_label(metrics, tier=tier, path=DEFAULT_THRESHOLDS_PATH)


def _mean_float(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 6) if values else None


def _variant_metric_for_horizon(variant: Dict[str, object], metric: str, fallback_metric: str, horizon: str = "ret60s") -> Optional[float]:
    eval_rows = variant.get("eval_rows", [])
    if isinstance(eval_rows, list):
        horizon_values = [
            value
            for eval_row in eval_rows
            if isinstance(eval_row, dict) and str(eval_row.get("horizon") or "") == horizon
            for value in [_metric_float(eval_row.get(metric))]
            if value is not None
        ]
        if horizon_values:
            return _mean_float(horizon_values)
    return _metric_float(variant.get(fallback_metric))


def _variant_small_ic_for_horizon(variant: Dict[str, object], horizon: str = "ret60s") -> Optional[float]:
    return _variant_metric_for_horizon(variant, "daily_ic", "mean_daily_ic", horizon=horizon)


def _factor_ic_bucket(abs_ic: Optional[float]) -> str:
    if abs_ic is None:
        return ""
    lower = math.floor(max(abs_ic, 0.0) * 100) / 100
    upper = lower + 0.01
    return f"{lower:.2f}-{upper:.2f}"


PROXY_VARIANT_SUFFIX_RE = re.compile(r"_(base|flip|roll\d+|z\d+|norm\d+|l\d+)$", re.I)


def _proxy_variant_root(variant: Dict[str, object]) -> str:
    template = str(variant.get("template") or variant.get("field") or "unknown")
    return PROXY_VARIANT_SUFFIX_RE.sub("", template) or template or "unknown"


def _proxy_variant_score(variant: Dict[str, object]) -> Tuple[float, float, float, float]:
    daily_ic = _variant_small_ic_for_horizon(variant)
    rankic = _variant_metric_for_horizon(variant, "daily_rankic", "mean_daily_rankic")
    qspread = _variant_metric_for_horizon(variant, "qspread_mean", "mean_qspread")
    valid_dates = _metric_float(variant.get("valid_dates") or variant.get("n_dates"))
    return (
        abs(daily_ic) if daily_ic is not None else -1.0,
        abs(rankic) if rankic is not None else -1.0,
        abs(qspread) if qspread is not None else -1.0,
        valid_dates if valid_dates is not None else 0.0,
    )


def _keep_best_proxy_variant(items: Dict[str, Dict[str, object]], key: str, candidate: Dict[str, object]) -> None:
    current = items.get(key)
    if current is None or _proxy_variant_score(candidate) > _proxy_variant_score(current):
        items[key] = candidate


def _best_proxy_variant_summary(row: Dict[str, object]) -> Optional[Dict[str, object]]:
    best: Optional[Dict[str, object]] = None
    best_abs_ic = -1.0
    for factor in _paper_factors_for_row(row):
        variants = factor.get("proxy_variants_v2", [])
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            ic = _variant_small_ic_for_horizon(variant)
            if ic is None:
                continue
            abs_ic = abs(ic)
            if abs_ic > best_abs_ic:
                best_abs_ic = abs_ic
                best = variant
    return best


def _proxy_backtest_badge(row: Dict[str, object], article_score: float) -> str:
    best = _best_proxy_variant_summary(row)
    if best is None:
        return '<span class="score score-muted">因子回测: NA</span>'
    ic = _variant_small_ic_for_horizon(best)
    pos_ic = _metric_float(best.get("positive_ic_ratio"))
    qspread = _metric_float(best.get("mean_qspread"))
    fidelity = html.escape(str(best.get("proxy_fidelity") or "unknown"))
    if ic is None:
        return '<span class="score score-muted">因子回测: NA</span>'
    return (
        f'<span class="score score-proxy">因子回测: IC {_format_metric(ic)} | IC&gt;0 {_format_ratio(pos_ic)} | QSpread {_format_metric(qspread)} | {fidelity}</span>'
    )


def _mean_metric(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 6) if values else None


def _ratio_metric(count: int, total: int) -> Optional[float]:
    return (count / total) if total else None


def _factor_field_summary(matches: List[Dict[str, object]]) -> Dict[str, object]:
    def values(name: str) -> List[float]:
        out: List[float] = []
        for row in matches:
            value = _metric_float(row.get(name))
            if value is not None:
                out.append(value)
        return out

    daily_ic = values("daily_ic")
    rankic = values("daily_rankic")
    global_ic = values("global_ic")
    global_rankic = values("global_rankic")
    qspread = values("qspread_mean")
    finite_ratio = values("finite_ratio")
    zero_ratio = values("zero_ratio")

    total_obs = 0
    for row in matches:
        try:
            total_obs += int(row.get("n_obs") or 0)
        except (TypeError, ValueError):
            pass

    return {
        "row_count": len(matches),
        "mean_daily_ic": _mean_metric(daily_ic),
        "positive_ic_ratio": _ratio_metric(sum(1 for x in daily_ic if x > 0), len(daily_ic)),
        "mean_daily_rankic": _mean_metric(rankic),
        "positive_rankic_ratio": _ratio_metric(sum(1 for x in rankic if x > 0), len(rankic)),
        "mean_global_ic": _mean_metric(global_ic),
        "positive_global_ic_ratio": _ratio_metric(sum(1 for x in global_ic if x > 0), len(global_ic)),
        "mean_global_rankic": _mean_metric(global_rankic),
        "positive_global_rankic_ratio": _ratio_metric(sum(1 for x in global_rankic if x > 0), len(global_rankic)),
        "mean_qspread": _mean_metric(qspread),
        "positive_qspread_ratio": _ratio_metric(sum(1 for x in qspread if x > 0), len(qspread)),
        "mean_finite_ratio": _mean_metric(finite_ratio),
        "mean_zero_ratio": _mean_metric(zero_ratio),
        "total_obs": total_obs,
        "ic_gt_001_ratio": _ratio_metric(sum(1 for x in daily_ic if x > 0.01), len(daily_ic)),
        "ic_gt_002_ratio": _ratio_metric(sum(1 for x in daily_ic if x > 0.02), len(daily_ic)),
        "ic_gt_003_ratio": _ratio_metric(sum(1 for x in daily_ic if x > 0.03), len(daily_ic)),
        "abs_ic_gt_0015_ratio": _ratio_metric(sum(1 for x in daily_ic if abs(x) > 0.015), len(daily_ic)),
        "abs_ic_gt_002_ratio": _ratio_metric(sum(1 for x in daily_ic if abs(x) > 0.02), len(daily_ic)),
    }


def _factor_field_summary_html(summary: Dict[str, object]) -> str:
    total_obs = html.escape(str(summary.get("total_obs", 0)))
    chips = [
        ("Daily IC", _format_metric(summary.get("mean_daily_ic"))),
        ("Daily IC&gt;0", _format_ratio(summary.get("positive_ic_ratio"))),
        ("Daily RankIC", _format_metric(summary.get("mean_daily_rankic"))),
        ("Daily RankIC&gt;0", _format_ratio(summary.get("positive_rankic_ratio"))),
        ("Global IC", _format_metric(summary.get("mean_global_ic"))),
        ("Global IC&gt;0", _format_ratio(summary.get("positive_global_ic_ratio"))),
        ("Global RankIC", _format_metric(summary.get("mean_global_rankic"))),
        ("Global RankIC&gt;0", _format_ratio(summary.get("positive_global_rankic_ratio"))),
        ("Mean QSpread", _format_metric(summary.get("mean_qspread"))),
        ("QSpread&gt;0", _format_ratio(summary.get("positive_qspread_ratio"))),
        ("Finite", _format_ratio(summary.get("mean_finite_ratio"))),
        ("Zero", _format_ratio(summary.get("mean_zero_ratio"))),
        ("Obs", total_obs),
        ("IC&gt;0.01", _format_ratio(summary.get("ic_gt_001_ratio"))),
        ("IC&gt;0.02", _format_ratio(summary.get("ic_gt_002_ratio"))),
        ("IC&gt;0.03", _format_ratio(summary.get("ic_gt_003_ratio"))),
        ("|IC|&gt;0.015", _format_ratio(summary.get("abs_ic_gt_0015_ratio"))),
        ("|IC|&gt;0.02", _format_ratio(summary.get("abs_ic_gt_002_ratio"))),
    ]
    return (
        '<div class="factor-value-metrics factor-value-summary">'
        + "".join(
            f'<span class="factor-value-metric"><strong>{label}</strong> {html.escape(value)}</span>'
            for label, value in chips
        )
        + "</div>"
    )


def _factor_quality_label(quality: object) -> Dict[str, str]:
    if not isinstance(quality, dict):
        return {"quality_class": "neutral", "quality_label": "质量：未检测", "direction_class": "neutral", "direction_label": "方向：-"}

    classification = str(quality.get("classification", ""))
    direction = str(quality.get("direction", ""))
    is_good = bool(quality.get("good_computable_factor"))

    if is_good:
        quality_class = "good"
        quality_label = "质量：好因子"
    elif classification == "usable_no_signal":
        quality_class = "neutral"
        quality_label = "质量：信号不足"
    elif classification == "mixed_direction":
        quality_class = "bad"
        quality_label = "质量：方向混合"
    elif classification == "failed_or_unusable":
        quality_class = "bad"
        quality_label = "质量：不可用"
    else:
        quality_class = "neutral"
        quality_label = "质量：未检测"

    if direction == "positive":
        direction_class = "positive"
        direction_label = "方向：正向"
    elif direction == "negative":
        direction_class = "negative"
        direction_label = "方向：反向"
    elif direction == "mixed":
        direction_class = "bad"
        direction_label = "方向：混合"
    else:
        direction_class = "neutral"
        direction_label = "方向：-"

    return {
        "quality_class": quality_class,
        "quality_label": quality_label,
        "direction_class": direction_class,
        "direction_label": direction_label,
    }


def _factor_quality_html(quality: object) -> str:
    labels = _factor_quality_label(quality)
    if isinstance(quality, dict):
        rule_count = html.escape(str(quality.get("signal_rule_count", "-")))
        reason = html.escape(str(quality.get("reason", "")))
        extra = f'<span class="factor-quality-badge neutral">规则：{rule_count}/6</span>'
        if reason:
            extra += f'<span class="factor-quality-badge neutral">{reason}</span>'
    else:
        extra = '<span class="factor-quality-badge neutral">等待运行质量分析模块</span>'
    return (
        '<div class="factor-quality-row">'
        f'<span class="factor-quality-badge {labels["quality_class"]}">{html.escape(labels["quality_label"])}</span>'
        f'<span class="factor-quality-badge {labels["direction_class"]}">{html.escape(labels["direction_label"])}</span>'
        f'{extra}'
        '</div>'
    )


def _factor_eval_summary_html(factor_eval: object) -> str:
    if not isinstance(factor_eval, dict):
        return ""
    summary = factor_eval.get("summary", {})
    if not isinstance(summary, dict) or not summary:
        return ""
    items = [
        ("Daily IC", _format_metric(summary.get("mean_daily_ic"))),
        ("Daily IC&gt;0", _format_ratio(summary.get("positive_ic_ratio"))),
        ("Daily RankIC", _format_metric(summary.get("mean_daily_rankic"))),
        ("Daily RankIC&gt;0", _format_ratio(summary.get("positive_rankic_ratio"))),
        ("Global IC", _format_metric(summary.get("mean_global_ic"))),
        ("Global RankIC", _format_metric(summary.get("mean_global_rankic"))),
        ("Mean QSpread", _format_metric(summary.get("mean_qspread"))),
        ("QSpread&gt;0", _format_ratio(summary.get("positive_qspread_ratio"))),
        ("Finite", _format_ratio(summary.get("mean_finite_ratio"))),
        ("Zero", _format_ratio(summary.get("mean_zero_ratio"))),
        ("Obs", _format_int_metric(summary.get("total_obs"))),
        ("IC&gt;0.01", _format_ratio(summary.get("ic_gt_001_ratio"))),
        ("IC&gt;0.02", _format_ratio(summary.get("ic_gt_002_ratio"))),
        ("IC&gt;0.03", _format_ratio(summary.get("ic_gt_003_ratio"))),
        ("|IC|&gt;0.015", _format_ratio(summary.get("abs_ic_gt_0015_ratio"))),
        ("|IC|&gt;0.02", _format_ratio(summary.get("abs_ic_gt_002_ratio"))),
    ]
    cells = "".join(
        f'<span class="factor-value-metric"><strong>{label}</strong> {html.escape(value)}</span>'
        for label, value in items
    )
    return f'<div class="factor-value-metrics">{cells}</div>'


def _factor_eval_unavailable_html(reason: str) -> str:
    reason_html = html.escape(reason)
    return f'<div class="factor-eval unavailable"><strong>因子数值：</strong>无法计算<span>（{reason_html}）</span></div>'


def _factor_eval_html(factor_eval: object, field: str) -> str:
    if not isinstance(factor_eval, dict):
        return ""
    status = str(factor_eval.get("status", ""))
    error = str(factor_eval.get("error", "") or "")
    eval_rows = factor_eval.get("rows", [])
    if status == "failed":
        return _factor_eval_unavailable_html(error or "评估任务失败")
    if not isinstance(eval_rows, list):
        return _factor_eval_unavailable_html("评估结果格式异常")
    matches = [row for row in eval_rows if isinstance(row, dict) and str(row.get("factor_field", "")) == field]
    if not matches:
        summary = factor_eval.get("summary", {})
        total_obs = summary.get("total_obs") if isinstance(summary, dict) else None
        if not eval_rows or total_obs in {0, "0"}:
            return _factor_eval_unavailable_html("没有可用行情数据或有效观测")
        return _factor_eval_unavailable_html("评估结果中没有该因子字段")
    items: List[str] = []
    for row in matches[:3]:
        horizon = html.escape(str(row.get("horizon", "")))
        code = html.escape(str(row.get("code", "")))
        n_obs = html.escape(str(row.get("n_obs", "")))
        daily_ic = _format_metric(row.get("daily_ic"))
        rankic = _format_metric(row.get("daily_rankic"))
        global_ic = _format_metric(row.get("global_ic"))
        global_rankic = _format_metric(row.get("global_rankic"))
        qspread = _format_metric(row.get("qspread_mean"))
        items.append(
            f"<div><strong>{code}</strong> {horizon} | n={n_obs} | Daily IC={daily_ic} | Daily RankIC={rankic} | Global IC={global_ic} | Global RankIC={global_rankic} | QSpread={qspread}</div>"
        )
    return f"<div class=\"factor-eval\">{''.join(items)}</div>"


def _factor_value_rows_html(factor_eval: object, field: str) -> str:
    if not isinstance(factor_eval, dict):
        return '<div class="factor-value-unavailable">因子数值：尚未运行因子评估</div>'

    status = str(factor_eval.get("status", ""))
    error = str(factor_eval.get("error", "") or "")
    stderr = str(factor_eval.get("stderr", "") or "")
    eval_rows = factor_eval.get("rows", [])

    if status != "ok":
        reason = error or "评估任务失败"
        if stderr:
            reason = f"{reason}；{stderr[:300]}"
        return f'<div class="factor-value-unavailable">因子评估失败：{html.escape(reason)}</div>'

    if not isinstance(eval_rows, list):
        return '<div class="factor-value-unavailable">因子数值：无法计算（评估结果格式异常）</div>'

    matches = [
        row
        for row in eval_rows
        if isinstance(row, dict) and str(row.get("factor_field", "")) == field
    ]

    if not matches:
        total_rows = len(eval_rows)
        reason = "评估结果中没有该因子字段"
        if total_rows == 0:
            reason = "因子评估无有效行 rows=0"
        return f'<div class="factor-value-unavailable">因子数值：无法计算（{html.escape(reason)}）</div>'

    summary = _factor_field_summary(matches)
    summary_html = _factor_field_summary_html(summary)

    blocks: List[str] = []
    for row in matches[:4]:
        code = html.escape(str(row.get("code", "")))
        horizon = html.escape(str(row.get("horizon", "")))
        n_obs = html.escape(str(row.get("n_obs", "")))
        daily_ic = _format_metric(row.get("daily_ic"))
        rankic = _format_metric(row.get("daily_rankic"))
        global_ic = _format_metric(row.get("global_ic"))
        global_rankic = _format_metric(row.get("global_rankic"))
        qspread = _format_metric(row.get("qspread_mean"))
        finite = _format_ratio(row.get("finite_ratio"))
        zero = _format_ratio(row.get("zero_ratio"))
        blocks.append(
            f'<div class="factor-value-metrics">'
            f'<span class="factor-value-metric"><strong>code</strong> {code}</span>'
            f'<span class="factor-value-metric"><strong>horizon</strong> {horizon}</span>'
            f'<span class="factor-value-metric"><strong>n</strong> {n_obs}</span>'
            f'<span class="factor-value-metric"><strong>Daily IC</strong> {daily_ic}</span>'
            f'<span class="factor-value-metric"><strong>Daily RankIC</strong> {rankic}</span>'
            f'<span class="factor-value-metric"><strong>Global IC</strong> {global_ic}</span>'
            f'<span class="factor-value-metric"><strong>Global RankIC</strong> {global_rankic}</span>'
            f'<span class="factor-value-metric"><strong>QSpread</strong> {qspread}</span>'
            f'<span class="factor-value-metric"><strong>Finite</strong> {finite}</span>'
            f'<span class="factor-value-metric"><strong>Zero</strong> {zero}</span>'
            f'</div>'
        )

    return summary_html + "".join(blocks)


def _factor_validation_html(title: str, factor_eval: object, field: str) -> str:
    if not isinstance(factor_eval, dict):
        return ""
    body = _factor_value_rows_html(factor_eval, field)
    return (
        '<div class="factor-value-detail factor-validation-block">'
        f'<strong>{html.escape(title)}</strong>'
        f'{body}'
        '</div>'
    )


def _candidate_value_unavailable_reason(candidate: Dict[str, object]) -> str:
    status = str(candidate.get("status", ""))
    template = str(candidate.get("template", ""))
    rationale = _normalize_text(str(candidate.get("rationale", "")))
    required_fields = candidate.get("required_fields", [])
    required_text = ", ".join(str(x) for x in required_fields) if isinstance(required_fields, list) else str(required_fields)
    proxy_strength = str(candidate.get("proxy_strength") or "")
    proxy_mappings = candidate.get("proxy_mappings", [])
    if status != "candidate" or template == "unsupported":
        detail = rationale or "当前字段白名单、模板或表达式无法覆盖该论文机制。"
        if proxy_strength in {"weak_proxy", "unsupported", "future_pipeline"}:
            variables = []
            if isinstance(proxy_mappings, list):
                variables = [str(item.get("canonical_variable") or item.get("paper_variable")) for item in proxy_mappings if isinstance(item, dict)]
            variable_text = f"；代理变量：{', '.join(variables[:6])}" if variables else ""
            detail = f"{detail} 代理强度={proxy_strength}{variable_text}。"
        if required_text:
            return f"无法计算：{detail} 需要字段/代理：{required_text}。"
        return f"无法计算：{detail}"
    return "尚未运行因子评估或评估结果未挂载。"


def _proxy_mapping_html(candidate: Dict[str, object]) -> str:
    mappings = candidate.get("proxy_mappings", [])
    proxy_strength = html.escape(str(candidate.get("proxy_strength") or "direct"))
    if not isinstance(mappings, list) or not mappings:
        return f'<div class="factor-value-detail"><strong>代理变量解析</strong>强度：{proxy_strength}；未识别到需注册表处理的论文抽象变量。</div>'
    rows = []
    for mapping in mappings[:8]:
        if not isinstance(mapping, dict):
            continue
        paper_variable = html.escape(str(mapping.get("paper_variable") or ""))
        canonical = html.escape(str(mapping.get("canonical_variable") or ""))
        strength = html.escape(str(mapping.get("proxy_strength") or ""))
        local_proxy = html.escape(str(mapping.get("local_proxy") or ""))
        loss = html.escape(str(mapping.get("approximation_loss") or mapping.get("future_pipeline") or ""))
        quality = html.escape(str(mapping.get("proxy_quality") or ""))
        validation_status = html.escape(str(mapping.get("validation_status") or ""))
        validation_reason = html.escape(str(mapping.get("validation_reason") or ""))
        when_context = html.escape(str(mapping.get("when_context") or ""))
        review_status = html.escape(str(mapping.get("review_status") or ""))
        data_requirement = html.escape(str(mapping.get("data_requirement") or ""))
        confidence = mapping.get("confidence")
        confidence_text = ""
        try:
            if confidence is not None and str(confidence).strip():
                confidence_text = f" | confidence: {float(confidence):.2f}"
        except (TypeError, ValueError):
            confidence_text = f" | confidence: {html.escape(str(confidence))}"
        required = mapping.get("required_fields", [])
        required_text = html.escape(", ".join(str(x) for x in required) if isinstance(required, list) else str(required))
        rows.append(
            "<li>"
            f"<code>{paper_variable}</code> → <code>{canonical}</code> "
            f"<span class=\"factor-value-badge {'ok' if strength in GENERATION_PROXY_STRENGTHS else 'warn'}\">{strength}</span>"
            f"<br>quality: {quality or '未标注'}{confidence_text}"
            f"<br>review: {review_status or 'unreviewed'}"
            f"<br>validation: {validation_status or '未校验'}{(' - ' + validation_reason) if validation_reason else ''}"
            f"{('<br>context: ' + when_context) if when_context else ''}"
            f"{('<br>data requirement: ' + data_requirement) if data_requirement else ''}"
            f"<br>local: {local_proxy or '无'}"
            f"<br>fields: {required_text or '无'}"
            f"<br>loss: {loss or '无'}"
            "</li>"
        )
    return (
        '<div class="factor-value-detail"><strong>代理变量解析</strong>'
        f'整体强度：{proxy_strength}<ul>{"".join(rows)}</ul></div>'
    )


def _factor_ic_flow_html(candidate: Dict[str, object], is_supported: bool) -> str:
    if not is_supported:
        reason = html.escape(_candidate_value_unavailable_reason(candidate))
        return f'<div class="factor-value-detail"><strong>数值与IC计算流程</strong>{reason}</div>'
    horizon = html.escape(str(candidate.get("horizon", "")))
    field = html.escape(str(candidate.get("field", "")))
    return (
        '<div class="factor-value-detail"><strong>数值与IC计算流程</strong>'
        '<ul>'
        f'<li>由候选表达式生成 <code>{field}.py</code> 因子文件。</li>'
        '<li>调用 <code>python -m src.factor.calculation.run_factor_eval</code> 交给 fac-eval 读取行情数据并逐标的计算因子值。</li>'
        f'<li>按目标 horizon（{horizon or "ret60s"}）与未来收益做 IC、RankIC、QSpread 等指标汇总。</li>'
        '<li>评估结果写入 <code>data/factor_results/*.json</code> 后在本模块展示；若本地无行情数据，则显示无法计算。</li>'
        '</ul></div>'
    )


def _computable_factor_values_html(row: Dict[str, object]) -> str:
    candidates = normalize_factor_candidates(row.get("factor_candidates", []))
    if not candidates:
        return ""
    factor_eval = row.get("factor_eval", {})
    factor_quality = row.get("factor_quality", {})
    if not isinstance(factor_quality, dict):
        factor_quality = {}
    medium1_results = row.get("factor_eval_medium1", {})
    if not isinstance(medium1_results, dict):
        medium1_results = {}
    cards: List[str] = []
    for candidate in candidates:
        is_supported = candidate.get("status") == "candidate"
        field = str(candidate.get("field", ""))
        field_html = html.escape(field)
        name = html.escape(str(candidate.get("name", "") or field))
        horizon = html.escape(str(candidate.get("horizon", "")))
        expression = html.escape(str(candidate.get("expression", "")))
        formula = html.escape(str(candidate.get("formula", "") or candidate.get("expression", "") or "待 LLM 补公式"))
        source_factor = html.escape(str(candidate.get("source_factor", "") or "未指明来源论文因子"))
        proxy_relation = html.escape(str(candidate.get("proxy_relation", "") or candidate.get("mechanism", "") or candidate.get("rationale", "") or "待 LLM 说明本地可计算代理与论文因子的关系"))
        preserved = html.escape(str(candidate.get("preserved_mechanism", "") or "待 LLM 说明保留的论文机制"))
        lost = html.escape(str(candidate.get("approximation_loss", "") or "待 LLM 说明近似或损失的部分"))
        calculation_steps = candidate.get("calculation_steps", [])
        steps_html = "".join(f"<li>{html.escape(str(step))}</li>" for step in calculation_steps if str(step).strip())
        input_fields = candidate.get("input_fields", []) or candidate.get("required_fields", [])
        input_text = html.escape(", ".join(str(x) for x in input_fields) if isinstance(input_fields, list) else str(input_fields))
        status_label = "可计算" if is_supported else "不可计算"
        status_class = "ok" if is_supported else "warn"
        proxy_html = _proxy_mapping_html(candidate)
        value_html = _factor_value_rows_html(factor_eval, field) if is_supported else (
            f'<div class="factor-value-unavailable">因子数值：{html.escape(_candidate_value_unavailable_reason(candidate))}</div>'
        )
        flow_html = _factor_ic_flow_html(candidate, is_supported)
        quality_html = _factor_quality_html(factor_quality.get(field)) if is_supported else ""
        medium1_html = _factor_validation_html("medium1 单因子验证", medium1_results.get(field), field) if is_supported else ""
        cards.append(
            f'<div class="factor-value-card">'
            f'<div class="factor-value-head"><span>{name} · <code>{field_html}</code></span><span class="factor-value-badge {status_class}">{status_label}</span></div>'
            f'<div class="factor-value-metrics"><span class="factor-value-metric"><strong>horizon</strong> {horizon}</span></div>'
            f'{quality_html}'
            f'<div class="factor-value-detail"><strong>来源论文高频因子</strong>{source_factor}</div>'
            f'<div class="factor-value-detail"><strong>公式</strong>{formula}</div>'
            f'<div class="factor-value-expression">可执行表达式：{expression or "无可执行表达式"}</div>'
            f'<div class="factor-value-detail"><strong>输入字段</strong>{input_text or "无"}</div>'
            f'<div class="factor-value-detail"><strong>计算流程</strong><ul>{steps_html or "<li>按可执行表达式生成本地代理因子。</li>"}</ul></div>'
            f'<div class="factor-value-detail"><strong>与论文高频因子的关系</strong>{proxy_relation}</div>'
            f'{proxy_html}'
            f'<div class="factor-value-detail"><strong>保留与损失</strong>保留：{preserved}<br>近似/损失：{lost}</div>'
            f'{flow_html}'
            f'{value_html}'
            f'{medium1_html}'
            f'</div>'
        )
    return (
        '<section class="factor-values-section">'
        '<div class="section-title">可计算因子<span>formula / relation / value / IC</span></div>'
        f'<div class="factor-value-list">{"".join(cards)}</div>'
        '</section>'
    )


def _format_factor_expression_html(expression: str) -> str:
    token_re = re.compile(r"rolling_[A-Za-z_]+|expanding_[A-Za-z_]+|cumsum|first|pct_change|zscore|abs|sign|log|diff|ema|[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?(?:e[+-]?\d+)?|[()+\-*/,.]", re.IGNORECASE)
    parts: List[str] = []
    last = 0
    for match in token_re.finditer(expression):
        if match.start() > last:
            parts.append(html.escape(expression[last:match.start()]))
        token = match.group(0)
        token_html = html.escape(token)
        if re.fullmatch(r"rolling_[A-Za-z_]+|expanding_[A-Za-z_]+|cumsum|first|pct_change|zscore|abs|sign|log|diff|ema", token, re.IGNORECASE):
            parts.append(f'<span class="fn">{token_html}</span>')
        elif re.fullmatch(r"\d+(?:\.\d+)?(?:e[+-]?\d+)?", token, re.IGNORECASE):
            parts.append(f'<span class="num">{token_html}</span>')
        elif token in {"+", "-", "*", "/"}:
            break_html = "<wbr>" if token in {"+", "-"} else ""
            parts.append(f'{break_html}<span class="op">{token_html}</span>')
        elif token in {"(", ")"}:
            parts.append(f'<span class="paren">{token_html}</span>')
        elif token == ",":
            parts.append('<span class="op">,</span><wbr>')
        elif token == ".":
            parts.append(token_html)
        else:
            parts.append(f'<span class="field">{token_html}</span>')
        last = match.end()
    if last < len(expression):
        parts.append(html.escape(expression[last:]))
    return "".join(parts)


def _hf_faithfulness_class(verdict: str) -> str:
    normalized = verdict.lower()
    if "faithful" in normalized:
        return "ok"
    if "translated" in normalized or "needs" in normalized or "review" in normalized:
        return "warn"
    if "reject" in normalized:
        return "bad"
    return "warn"


def _hf_faithfulness_render_indexes() -> Tuple[Dict[Tuple[str, str], Dict[str, object]], Dict[Tuple[str, str], Dict[str, object]]]:
    global _HF_FAITHFULNESS_RENDER_CACHE
    if _HF_FAITHFULNESS_RENDER_CACHE is not None:
        return _HF_FAITHFULNESS_RENDER_CACHE
    root = Path(__file__).resolve().parents[2]

    def load_index(path: Path) -> Dict[Tuple[str, str], Dict[str, object]]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        records = payload.get("records", []) if isinstance(payload, dict) else []
        indexed: Dict[Tuple[str, str], Dict[str, object]] = {}
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            article = record.get("article") if isinstance(record.get("article"), dict) else {}
            title = str(article.get("title") or record.get("title") or record.get("article_title") or "")
            factor_id = str(record.get("factor_id") or "")
            factor_index = factor_id.rsplit(":", 1)[-1] if factor_id else str(record.get("factor_index") or "")
            if title and factor_index:
                indexed[(title, factor_index)] = record
        return indexed

    _HF_FAITHFULNESS_RENDER_CACHE = (
        load_index(root / "reports" / "hf_factor_faithfulness_audit.json"),
        load_index(root / "reports" / "hf_factor_faithfulness_llm_review.json"),
    )
    return _HF_FAITHFULNESS_RENDER_CACHE


def _attach_render_time_hf_faithfulness(row: Dict[str, object], factor_index: int, factor: Dict[str, object]) -> None:
    audit_index, llm_index = _hf_faithfulness_render_indexes()
    title = str(row.get("title") or "")
    index_text = str(factor_index)
    if "hf_faithfulness_audit" not in factor and (title, index_text) in audit_index:
        factor["hf_faithfulness_audit"] = audit_index[(title, index_text)]
    if "hf_faithfulness_llm_review" not in factor and (title, index_text) in llm_index:
        factor["hf_faithfulness_llm_review"] = llm_index[(title, index_text)]


def _hf_faithfulness_html(factor: Dict[str, object]) -> str:
    audit = factor.get("hf_faithfulness_audit") if isinstance(factor.get("hf_faithfulness_audit"), dict) else {}
    llm_review = factor.get("hf_faithfulness_llm_review") if isinstance(factor.get("hf_faithfulness_llm_review"), dict) else {}
    if not audit and not llm_review:
        return (
            '<div class="factor-detail"><strong>忠实度判断</strong>'
            '<span class="factor-value-badge warn">待审核</span> 尚未生成离线忠实度记录；建议先运行 three-AI 忠实度审核模块。'
            '<br>LLM 忠实度复核：未运行；该复核应独立读取论文资料、AI原始因子和最终公式，输出解释性 verdict，不直接改写因子。'
            '</div>'
        )
    parts: List[str] = []
    if audit:
        auto_verdict = str(audit.get("auto_verdict") or "needs_review")
        human_review = audit.get("human_review") if isinstance(audit.get("human_review"), dict) else {}
        human_verdict = str(human_review.get("verdict") or "未审核") if human_review else "未审核"
        verdict = str(audit.get("final_verdict") or auto_verdict)
        final_use_status = str(audit.get("final_use_status") or "")
        score = audit.get("final_score", audit.get("auto_total", ""))
        risks = [str(item) for item in audit.get("risk_flags", []) if str(item)] if isinstance(audit.get("risk_flags"), list) else []
        checks = audit.get("automatic_checks") if isinstance(audit.get("automatic_checks"), dict) else {}
        semantic_conflicts = checks.get("semantic_context_conflicts", []) if isinstance(checks, dict) else []
        semantic_text = ""
        if isinstance(semantic_conflicts, list) and semantic_conflicts:
            conflict_items = []
            for conflict in semantic_conflicts[:3]:
                if isinstance(conflict, dict):
                    term = html.escape(str(conflict.get("term") or ""))
                    reason = html.escape(str(conflict.get("reason") or ""))
                    conflict_items.append(f"<li><code>{term}</code>: {reason}</li>")
            if conflict_items:
                semantic_text = f'<div>同词语境风险：<ul>{"".join(conflict_items)}</ul></div>'
        risk_text = html.escape(", ".join(risks[:8]) if risks else "无自动风险")
        human_class = _hf_faithfulness_class(human_verdict) if human_review else "warn"
        parts.append(
            '<div class="factor-detail"><strong>忠实度判断</strong>'
            f'<span class="factor-value-badge {_hf_faithfulness_class(auto_verdict)}">自动：{html.escape(auto_verdict)}</span> '
            f'<span class="factor-value-badge {human_class}">人工：{html.escape(human_verdict)}</span> '
            f'<span class="factor-value-badge {_hf_faithfulness_class(verdict)}">最终：{html.escape(verdict)}</span> '
            f'<span class="factor-value-badge {_hf_faithfulness_class(final_use_status)}">使用：{html.escape(final_use_status or "needs_revision")}</span> '
            f'分数：{html.escape(str(score))}/18<br>'
            f'自动风险：{risk_text}'
            f'{semantic_text}'
            '</div>'
        )
    if llm_review:
        verdict = str(llm_review.get("verdict") or llm_review.get("final_verdict") or "llm_review_available")
        score = str(llm_review.get("score") or llm_review.get("faithfulness_score") or "未标注")
        model = str(llm_review.get("model") or llm_review.get("review_model") or "未标注")
        rationale = html.escape(str(llm_review.get("rationale") or llm_review.get("reason") or ""))
        parts.append(
            '<div class="factor-detail"><strong>LLM 忠实度复核</strong>'
            f'<span class="factor-value-badge {_hf_faithfulness_class(verdict)}">{html.escape(verdict)}</span> '
            f'模型：{html.escape(model)} | 分数：{html.escape(score)}'
            f'{("<br>理由：" + rationale) if rationale else ""}'
            '</div>'
        )
    else:
        parts.append(
            '<div class="factor-detail"><strong>LLM 忠实度复核</strong>'
            '<span class="factor-value-badge warn">未运行</span> 预留给新的 LLM 审核调用；输入应包含中文资料包、AI原始因子、最终custom_formula和proxy映射，输出只写报告，不自动覆盖因子。'
            '</div>'
        )
    return "".join(parts)


def _structured_summary_html(raw: object) -> str:
    summary = _normalize_structured_summary(raw)
    if not summary:
        return ""
    labels = {
        "problem": "问题",
        "method": "方法",
        "data": "数据",
        "author_claim": "作者主张",
        "limitations": "局限",
        "critical_assessment": "批判性评估",
        "missing_tests": "缺失验证",
        "key_results": "关键结果",
    }
    blocks = []
    for key, label in labels.items():
        text = summary.get(key, "")
        if not text:
            continue
        blocks.append(
            f'<div class="summary-block {key}"><div class="summary-label">{label}</div>'
            f'<div class="summary-text">{html.escape(text)}</div></div>'
        )
    if not blocks:
        return ""
    return f'<section class="read-section"><h4 class="read-section-title">结构化摘要</h4><div class="structured-summary">{"".join(blocks)}</div></section>'


def _factor_candidate_cards(row: Dict[str, object]) -> str:
    factors = _paper_factors_for_row(row)
    dropped_factors = row.get("dropped_paper_hf_factors") if isinstance(row.get("dropped_paper_hf_factors"), list) else []
    if not factors:
        if dropped_factors:
            return f"<p><strong>可落地高频因子：</strong>无</p><div class='factor-detail'><strong>已过滤中间推导/校准项</strong>{len(dropped_factors)} 个</div>"
        return ""

    items: List[str] = []
    for factor_index, factor in enumerate(factors):
        _attach_render_time_hf_faithfulness(row, factor_index, factor)
        name = html.escape(str(factor.get("name", "")))
        frequency = html.escape(str(factor.get("frequency", "") or "待定"))
        mechanism_formula = html.escape(str(factor.get("mechanism_formula", "")))
        meaning = html.escape(str(factor.get("meaning", "")))
        mechanism_type = html.escape(str(factor.get("mechanism_type", "") or "unknown"))
        novelty_reason = html.escape(str(factor.get("novelty_reason", "")))
        classic_baseline = html.escape(str(factor.get("classic_baseline", "")))
        ideal_fields = factor.get("ideal_input_fields", [])
        ideal_text = html.escape(", ".join(str(x) for x in ideal_fields) if isinstance(ideal_fields, list) else str(ideal_fields))
        variable_roles = factor.get("variable_roles", [])
        variable_roles_html = ""
        if isinstance(variable_roles, list) and variable_roles:
            role_items = []
            for role in variable_roles[:8]:
                if isinstance(role, dict):
                    variable = html.escape(str(role.get("variable") or ""))
                    role_text = html.escape(str(role.get("role") or ""))
                    role_items.append(f"<li><code>{variable}</code>: {role_text}</li>")
                elif role:
                    role_items.append(f"<li>{html.escape(str(role))}</li>")
            if role_items:
                variable_roles_html = f'<div class="factor-detail"><strong>变量角色</strong><ul>{"".join(role_items)}</ul></div>'
        unobservable_variables = factor.get("unobservable_variables", [])
        minimum_data_needed = factor.get("minimum_data_needed", [])
        unobservable_text = html.escape(", ".join(str(x) for x in unobservable_variables) if isinstance(unobservable_variables, list) else str(unobservable_variables))
        minimum_data_text = html.escape(", ".join(str(x) for x in minimum_data_needed) if isinstance(minimum_data_needed, list) else str(minimum_data_needed))
        mechanism = html.escape(str(factor.get("paper_mechanism", "") or factor.get("meaning", "")))
        evidence = html.escape(str(factor.get("source_evidence", "")))
        formula_source_type = html.escape(str(factor.get("formula_source_type", "unknown") or "unknown"))
        formula_source_quote = html.escape(str(factor.get("formula_source_quote", "")))
        formula_role_in_paper = html.escape(str(factor.get("formula_role_in_paper", "unknown") or "unknown"))
        why_actionable = html.escape(str(factor.get("why_this_formula_is_actionable", "")))
        whole_paper_formula = html.escape(str(factor.get("whole_paper_formula", "")))
        whole_paper_basis = factor.get("whole_paper_basis") if isinstance(factor.get("whole_paper_basis"), dict) else {}
        whole_paper_basis_html = ""
        if any(str(whole_paper_basis.get(key) or "").strip() for key in ("problem", "method", "final_result_or_formula", "limitations_or_data")):
            whole_paper_basis_html = (
                f"<br>全文依据: problem={html.escape(str(whole_paper_basis.get('problem') or '未给出'))}; "
                f"method={html.escape(str(whole_paper_basis.get('method') or '未给出'))}; "
                f"final={html.escape(str(whole_paper_basis.get('final_result_or_formula') or '未给出'))}; "
                f"limits/data={html.escape(str(whole_paper_basis.get('limitations_or_data') or '未给出'))}"
            )
        procedure = html.escape(str(factor.get("procedure", "")))
        rationale = html.escape(str(factor.get("rationale", "")))
        stored_mappings = factor.get("proxy_mappings", [])
        stored_unresolved = factor.get("unresolved_proxy_variables", [])
        if isinstance(stored_mappings, list):
            proxy_mappings = [item for item in stored_mappings if isinstance(item, dict)]
            unresolved_variables = _normalize_string_list(stored_unresolved, limit=12)
            proxy_status = _normalize_text(str(factor.get("proxy_status") or ""))
            proxy_status_reason = _normalize_text(str(factor.get("proxy_status_reason") or ""))
            if not proxy_status:
                proxy_status, proxy_status_reason = _paper_factor_proxy_status(proxy_mappings, unresolved_variables)
        else:
            proxy_mappings, unresolved_variables = _resolve_paper_factor_proxy_mappings(factor)
            proxy_status, proxy_status_reason = _paper_factor_proxy_status(proxy_mappings, unresolved_variables)
        proxy_status_class = "ok" if proxy_status in {"fully_computable", "partially_computable"} else "warn"
        proxy_items: List[str] = []
        for mapping in proxy_mappings[:10]:
            paper_variable = html.escape(str(mapping.get("paper_variable") or ""))
            canonical = html.escape(str(mapping.get("canonical_variable") or ""))
            strength = html.escape(str(mapping.get("proxy_strength") or ""))
            local_proxy = html.escape(str(mapping.get("local_proxy") or ""))
            required = mapping.get("required_fields", [])
            required_text = html.escape(", ".join(str(x) for x in required) if isinstance(required, list) else str(required))
            loss = html.escape(str(mapping.get("approximation_loss") or mapping.get("future_pipeline") or ""))
            quality = html.escape(str(mapping.get("proxy_quality") or ""))
            validation_status = html.escape(str(mapping.get("validation_status") or ""))
            validation_reason = html.escape(str(mapping.get("validation_reason") or ""))
            when_context = html.escape(str(mapping.get("when_context") or ""))
            review_status = html.escape(str(mapping.get("review_status") or ""))
            data_requirement = html.escape(str(mapping.get("data_requirement") or ""))
            confidence = mapping.get("confidence")
            confidence_text = ""
            try:
                if confidence is not None and str(confidence).strip():
                    confidence_text = f" | confidence: {float(confidence):.2f}"
            except (TypeError, ValueError):
                confidence_text = f" | confidence: {html.escape(str(confidence))}"
            badge_class = "ok" if strength in GENERATION_PROXY_STRENGTHS else "warn"
            proxy_items.append(
                "<li>"
                f"<code>{paper_variable}</code> → <code>{canonical}</code> "
                f"<span class=\"factor-value-badge {badge_class}\">{strength}</span>"
                f"<br>quality: {quality or '未标注'}{confidence_text}"
                f"<br>review: {review_status or 'unreviewed'}"
                f"<br>validation: {validation_status or '未校验'}{(' - ' + validation_reason) if validation_reason else ''}"
                f"{('<br>context: ' + when_context) if when_context else ''}"
                f"{('<br>data requirement: ' + data_requirement) if data_requirement else ''}"
                f"<br>local: {local_proxy or '无'}"
                f"<br>fields: {required_text or '无'}"
                f"<br>loss: {loss or '无'}"
                "</li>"
            )
        unresolved_html = ""
        if unresolved_variables:
            unresolved_html = (
                '<div class="factor-detail"><strong>待归类变量</strong>'
                f'{html.escape(", ".join(unresolved_variables[:10]))}</div>'
            )
        proxy_html = (
            '<div class="factor-detail">'
            '<strong>本地代理状态</strong>'
            f'<span class="factor-value-badge {proxy_status_class}">{html.escape(proxy_status)}</span> '
            f'{html.escape(proxy_status_reason)}'
            f'<ul>{"".join(proxy_items) or "<li>未命中已注册变量；建议进入变量审计。</li>"}</ul>'
            '</div>'
            f'{unresolved_html}'
        )
        variants = factor.get("proxy_variants_v2", [])
        variant_html = ""
        if isinstance(variants, list) and variants:
            variant_items = []

            def render_eval_block(eval_payload: Dict[str, object], tier: str, title: str) -> str:
                quality = _paper_hf_proxy_quality_label(eval_payload, tier=tier)
                eval_cells = [
                    ("Daily IC", _format_metric(eval_payload.get("mean_daily_ic"))),
                    ("Daily IC&gt;0", _format_ratio(eval_payload.get("positive_ic_ratio"))),
                    ("Daily RankIC", _format_metric(eval_payload.get("mean_daily_rankic"))),
                    ("Daily RankIC&gt;0", _format_ratio(eval_payload.get("positive_rankic_ratio"))),
                    ("Global IC", _format_metric(eval_payload.get("mean_global_ic"))),
                    ("Global IC&gt;0", _format_ratio(eval_payload.get("positive_global_ic_ratio"))),
                    ("Global RankIC", _format_metric(eval_payload.get("mean_global_rankic"))),
                    ("Global RankIC&gt;0", _format_ratio(eval_payload.get("positive_global_rankic_ratio"))),
                    ("Mean QSpread", _format_metric(eval_payload.get("mean_qspread"))),
                    ("QSpread&gt;0", _format_ratio(eval_payload.get("positive_qspread_ratio"))),
                    ("Finite", _format_ratio(eval_payload.get("mean_finite_ratio"))),
                    ("Zero", _format_ratio(eval_payload.get("mean_zero_ratio"))),
                    ("Obs", _format_int_metric(eval_payload.get("total_obs"))),
                    ("IC&gt;0.01", _format_ratio(eval_payload.get("ic_gt_001_ratio"))),
                    ("IC&gt;0.02", _format_ratio(eval_payload.get("ic_gt_002_ratio"))),
                    ("IC&gt;0.03", _format_ratio(eval_payload.get("ic_gt_003_ratio"))),
                    ("|IC|&gt;0.015", _format_ratio(eval_payload.get("abs_ic_gt_0015_ratio"))),
                    ("|IC|&gt;0.02", _format_ratio(eval_payload.get("abs_ic_gt_002_ratio"))),
                ]
                eval_summary_html = '<div class="factor-value-metrics">' + "".join(
                    f'<span class="factor-value-metric"><strong>{label}</strong> {html.escape(value)}</span>'
                    for label, value in eval_cells
                ) + "</div>"
                eval_rows_html = []
                eval_rows = eval_payload.get("eval_rows", [])
                horizon_rows_html = []
                if isinstance(eval_rows, list):
                    horizon_groups: Dict[str, List[Dict[str, object]]] = {}
                    for eval_row in eval_rows:
                        if isinstance(eval_row, dict):
                            horizon_groups.setdefault(str(eval_row.get("horizon") or "unknown"), []).append(eval_row)
                    for horizon, horizon_group in sorted(horizon_groups.items()):
                        horizon_summary = _factor_field_summary(horizon_group)
                        horizon_rows_html.append(
                            '<div class="factor-value-metrics">'
                            f'<span class="factor-value-metric"><strong>horizon</strong> {html.escape(horizon)}</span>'
                            f'<span class="factor-value-metric"><strong>Daily IC</strong> {_format_metric(horizon_summary.get("mean_daily_ic"))}</span>'
                            f'<span class="factor-value-metric"><strong>Daily RankIC</strong> {_format_metric(horizon_summary.get("mean_daily_rankic"))}</span>'
                            f'<span class="factor-value-metric"><strong>Global IC</strong> {_format_metric(horizon_summary.get("mean_global_ic"))}</span>'
                            f'<span class="factor-value-metric"><strong>Global RankIC</strong> {_format_metric(horizon_summary.get("mean_global_rankic"))}</span>'
                            f'<span class="factor-value-metric"><strong>QSpread</strong> {_format_metric(horizon_summary.get("mean_qspread"))}</span>'
                            f'<span class="factor-value-metric"><strong>Obs</strong> {html.escape(str(horizon_summary.get("total_obs", 0)))}</span>'
                            '</div>'
                        )
                    for eval_row in eval_rows[:20]:
                        if not isinstance(eval_row, dict):
                            continue
                        eval_rows_html.append(
                            '<div class="factor-value-metrics">'
                            f'<span class="factor-value-metric"><strong>code</strong> {html.escape(str(eval_row.get("code", "")))}</span>'
                            f'<span class="factor-value-metric"><strong>horizon</strong> {html.escape(str(eval_row.get("horizon", "")))}</span>'
                            f'<span class="factor-value-metric"><strong>n</strong> {html.escape(str(eval_row.get("n_obs", "")))}</span>'
                            f'<span class="factor-value-metric"><strong>Daily IC</strong> {_format_metric(eval_row.get("daily_ic"))}</span>'
                            f'<span class="factor-value-metric"><strong>Daily RankIC</strong> {_format_metric(eval_row.get("daily_rankic"))}</span>'
                            f'<span class="factor-value-metric"><strong>Global IC</strong> {_format_metric(eval_row.get("global_ic"))}</span>'
                            f'<span class="factor-value-metric"><strong>Global RankIC</strong> {_format_metric(eval_row.get("global_rankic"))}</span>'
                            f'<span class="factor-value-metric"><strong>QSpread</strong> {_format_metric(eval_row.get("qspread_mean"))}</span>'
                            f'<span class="factor-value-metric"><strong>Finite</strong> {_format_ratio(eval_row.get("finite_ratio"))}</span>'
                            f'<span class="factor-value-metric"><strong>Zero</strong> {_format_ratio(eval_row.get("zero_ratio"))}</span>'
                            '</div>'
                        )
                eval_details = ""
                if eval_rows_html:
                    total_eval_rows = len(eval_rows) if isinstance(eval_rows, list) else len(eval_rows_html)
                    eval_details = (
                        f'<details class="paper-hf-row-details"><summary>{html.escape(title)}逐股票/期限明细（显示 {len(eval_rows_html)} / {total_eval_rows} 行）</summary>'
                        f'{"".join(eval_rows_html)}</details>'
                    )
                return (
                    '<div class="paper-hf-variant-section">'
                    f'<strong>{html.escape(title)}</strong> '
                    f'<span class="factor-value-badge {html.escape(quality["class"])}">{html.escape(quality["label"])}</span>'
                    f'<div>Quality reason: {html.escape(quality["reason"])}</div>'
                    f'{eval_summary_html}{"".join(horizon_rows_html)}{eval_details}</div>'
                )

            for variant in variants[:8]:
                if not isinstance(variant, dict):
                    continue
                field = html.escape(str(variant.get("field") or ""))
                template = html.escape(str(variant.get("template") or ""))
                formula = html.escape(str(variant.get("formula") or ""))
                fidelity = html.escape(str(variant.get("proxy_fidelity") or ""))
                proxy_loss = html.escape(str(variant.get("proxy_loss") or ""))
                small_quality = _paper_hf_proxy_quality_label(variant, tier="small")
                summary_html = render_eval_block(variant, "small", "Small评估指标")
                medium_html = ""
                medium_eval = variant.get("medium1_eval")
                if isinstance(medium_eval, dict):
                    medium_html = render_eval_block(medium_eval, "medium", "Medium1复检指标")
                large_html = ""
                large_eval = variant.get("large1_eval")
                if isinstance(large_eval, dict):
                    large_html = render_eval_block(large_eval, "large", "Large1复检指标")
                variant_items.append(
                    '<div class="paper-hf-variant">'
                    f'<div class="paper-hf-variant-title"><code>{field}</code><span class="factor-value-badge ok">{template}</span><span class="factor-value-badge {html.escape(small_quality["class"])}">{html.escape(small_quality["label"])}</span></div>'
                    '<div class="paper-hf-variant-section"><strong>这个可执行变体是什么</strong>'
                    f'本地字段名：<code>{field}</code><br>可执行代理公式：<code>{formula or "未记录"}</code><br>代理忠实度：{fidelity or "未标注"}</div>'
                    '<div class="paper-hf-variant-section"><strong>与原论文高频因子的区别</strong>'
                    f'原论文HF机制强调：{mechanism or meaning or "未标注"}<br>'
                    f'本地代理只能使用当前行情字段和白名单函数实现，因此使用模板 <code>{template}</code> 近似。'
                    f'主要偏差/损失：{proxy_loss or "未记录"}</div>'
                    f'{summary_html}'
                    f'{medium_html}'
                    f'{large_html}'
                    '</div>'
                )
            if variant_items:
                variant_html = (
                    '<div class="factor-detail"><strong>V2确定性代理变体</strong>'
                    '<div>由Python根据paper_hf_factor与proxy registry生成；不调用LLM。</div>'
                    f'{"".join(variant_items)}</div>'
                )
        meta_html = (
            f'<div class="factor-meta">'
            f'<span class="factor-chip"><strong>frequency</strong>{frequency}</span>'
            f'<span class="factor-chip"><strong>mechanism</strong>{mechanism_type}</span>'
            f'<span class="factor-chip"><strong>classic</strong>{classic_baseline or "待标注"}</span>'
            f'<span class="factor-chip"><strong>mechanism_fields</strong>{ideal_text or "待定"}</span>'
            f'</div>'
        )
        formula_html = f'<div class="factor-expression"><div class="factor-expression-label"><span>final factor formula</span><span>paper/derived</span></div><code class="factor-formula">{mechanism_formula}</code></div>' if mechanism_formula else ""
        formula_source_html = f'<div class="factor-detail"><strong>公式来源</strong>{formula_source_type} / {formula_role_in_paper}<br>{formula_source_quote or "未给出原文摘录"}<br>全文机制公式: {whole_paper_formula or "未给出"}<br>actionable: {why_actionable or "未说明"}{whole_paper_basis_html}</div>' if mechanism_formula or formula_source_quote or why_actionable or whole_paper_formula else ""
        novelty_html = f'<div class="factor-detail"><strong>新鲜性/经典基线</strong>{novelty_reason or "未标注"}<br>classic baseline: {classic_baseline or "未标注"}</div>' if novelty_reason or classic_baseline else ""
        data_need_html = ""
        if unobservable_text or minimum_data_text:
            data_need_html = f'<div class="factor-detail"><strong>不可观测变量/最小数据</strong>{unobservable_text or "无"}<br>minimum data: {minimum_data_text or "未标注"}</div>'
        evidence_html = f'<div class="factor-rationale">证据：{evidence}</div>' if evidence else ""
        procedure_html = f'<div class="factor-detail"><strong>计算/落地过程</strong>{procedure}</div>' if procedure else ""
        rationale_html = f'<div class="factor-detail"><strong>因子理由</strong>{rationale}</div>' if rationale and rationale != meaning else ""
        faithfulness_html = _hf_faithfulness_html(factor)
        items.append(
            f"""
<div class="factor-card">
  <div class="factor-head"><span class="factor-name">{name}</span></div>
  {meta_html}
  {formula_html}
    {formula_source_html}
    {faithfulness_html}
  <div class="factor-rationale">{meaning}</div>
  <div class="factor-detail"><strong>对应论文机制</strong>{mechanism}</div>
    {novelty_html}
    {variable_roles_html}
    {data_need_html}
        {proxy_html}
        {variant_html}
    {procedure_html}
    {rationale_html}
  {evidence_html}
</div>
"""
        )

    dropped_html = f"<div class='factor-detail'><strong>已过滤中间推导/校准项</strong>{len(dropped_factors)} 个</div>" if dropped_factors else ""
    return f"<p><strong>可落地高频因子：</strong></p><div class='factor-list'>{''.join(items)}</div>{dropped_html}"


def _candidate_window(candidate: Dict[str, object], default: int = 20) -> int:
    raw = str(candidate.get("lookback") or "")
    match = re.search(r"\d+", raw)
    if not match:
        return default
    return max(1, min(2000, int(match.group(0))))


def _paired_levels(required_fields: List[str], pattern: object, left_prefix: str, right_prefix: str) -> List[int]:
    levels: Dict[int, set[str]] = {}
    for field in required_fields:
        match = pattern.match(field)
        if not match:
            continue
        prefix, level_text = match.groups()
        levels.setdefault(int(level_text), set()).add(prefix)
    paired = [level for level, prefixes in levels.items() if {left_prefix, right_prefix}.issubset(prefixes)]
    return sorted(paired) or [1]


def _csv_string_literal(values: List[str]) -> str:
    return ", ".join(json.dumps(value) for value in values)


def _compile_llm_expression(expression: str) -> Optional[str]:
    expr = _normalize_text(expression)
    if not expr or len(expr) > 320:
        return None
    if _has_future_return_reference(expr):
        return None
    if re.search(r"[^0-9A-Za-z_\s\+\-\*/\.\(\),]", expr):
        return None
    if expr.count("(") != expr.count(")"):
        return None
    depth = 0
    max_depth = 0
    for char in expr:
        if char == "(":
            depth += 1
            max_depth = max(max_depth, depth)
        elif char == ")":
            depth -= 1
            if depth < 0:
                return None
    if max_depth > 8:
        return None
    if len(EXPRESSION_FUNC_RE.findall(expr)) > 8:
        return None
    for func_call in EXPRESSION_FUNC_RE.finditer(expr):
        tail = expr[func_call.end() : func_call.end() + 80]
        window_match = re.search(r",\s*(\d+)", tail)
        if window_match and int(window_match.group(1)) > 2000:
            return None

    protected: Dict[str, str] = {}

    def _protect(match: re.Match[str]) -> str:
        func = match.group(1)
        token = f"__FUNC_{len(protected)}__"
        protected[token] = func
        return f"{token}("

    masked = EXPRESSION_FUNC_RE.sub(_protect, expr)
    names = set(EXPRESSION_FIELD_RE.findall(masked))
    allowed_tokens = set(protected) | {"nan", "inf"}
    unknown = [name for name in names if name not in ALLOWED_FACTOR_FIELDS and name not in allowed_tokens]
    if unknown:
        return None

    compiled = masked
    for field in sorted((name for name in names if name in ALLOWED_FACTOR_FIELDS), key=len, reverse=True):
        compiled = re.sub(rf"\b{re.escape(field)}\b", f'_num(df, "{field}")', compiled)

    for token, func in protected.items():
        if func not in ALLOWED_EXPRESSION_FUNCS:
            return None
        compiled = compiled.replace(token, f"_{func}")
    return compiled


def _render_factor_formula(candidate: Dict[str, object]) -> str:
    template = str(candidate.get("template", ""))
    required_fields = [str(x) for x in candidate.get("required_fields", []) if isinstance(x, str)]
    window = _candidate_window(candidate)
    expression_formula = _compile_llm_expression(str(candidate.get("expression", "")))
    if expression_formula:
        return expression_formula

    if template in {"order_book_imbalance", "depth_pressure", "volume_pressure"}:
        if {"totalDeputeBuy", "totalDeputeSell"}.issubset(required_fields):
            return '_safe_div(_num(df, "totalDeputeBuy") - _num(df, "totalDeputeSell"), _num(df, "totalDeputeBuy") + _num(df, "totalDeputeSell"))'
        levels = _paired_levels(required_fields, VOLUME_LEVEL_RE, "bidV", "askV")
        bid_cols = [f"bidV{level}" for level in levels]
        ask_cols = [f"askV{level}" for level in levels]
        return (
            f"_safe_div(_sum_cols(df, [{_csv_string_literal(bid_cols)}]) - _sum_cols(df, [{_csv_string_literal(ask_cols)}]), "
            f"_sum_cols(df, [{_csv_string_literal(bid_cols)}]) + _sum_cols(df, [{_csv_string_literal(ask_cols)}]))"
        )

    if template == "bid_ask_spread":
        levels = _paired_levels(required_fields, PRICE_LEVEL_RE, "bidP", "askP")
        level = levels[0]
        bid_col = f"bidP{level}"
        ask_col = f"askP{level}"
        return f'_safe_div(_num(df, "{ask_col}") - _num(df, "{bid_col}"), (_num(df, "{ask_col}") + _num(df, "{bid_col}")) / 2.0)'

    if template == "weighted_mid_price_deviation":
        return (
            '_safe_div(_safe_div(_num(df, "askP1") * _num(df, "bidV1") + _num(df, "bidP1") * _num(df, "askV1"), '
            '_num(df, "bidV1") + _num(df, "askV1")) - _num(df, "close"), _num(df, "close"))'
        )

    if template == "trade_intensity":
        return f'_num(df, "volume").rolling(window={window}, min_periods=1).sum().fillna(0.0)'

    if template == "money_flow":
        return f'_safe_div(_num(df, "money").rolling(window={window}, min_periods=1).sum(), _num(df, "volume").rolling(window={window}, min_periods=1).sum())'

    if template == "short_return_momentum":
        return f'_num(df, "close").pct_change({window}).replace([np.inf, -np.inf], np.nan).fillna(0.0)'

    if template == "short_return_reversal":
        return f'(-_num(df, "close").pct_change({window})).replace([np.inf, -np.inf], np.nan).fillna(0.0)'

    return 'pd.Series(0.0, index=df.index)'


def _generated_factor_path(row: Dict[str, object], generated_dir: Path) -> Path:
    dedup_key = _normalize_text(str(row.get("dedup_key", ""))).lower()
    if not re.fullmatch(r"[0-9a-f]{16,64}", dedup_key):
        dedup_key = hashlib.sha256(_analysis_cache_key(row).encode("utf-8")).hexdigest()
    return generated_dir / f"{dedup_key}.py"


def _render_factor_file(row: Dict[str, object]) -> Optional[str]:
    candidates = [c for c in normalize_factor_candidates(row.get("factor_candidates", [])) if c.get("status") == "candidate"]
    if not candidates:
        return None

    used_fields: set[str] = set()
    assignments: List[str] = []
    output_fields: List[str] = []
    for candidate in candidates:
        field = str(candidate.get("field", ""))
        if not field or field in used_fields:
            continue
        used_fields.add(field)
        output_fields.append(field)
        assignments.append(f'    out["{field}"] = ({_render_factor_formula(candidate)}).replace([np.inf, -np.inf], np.nan).fillna(0.0)')

    if not output_fields:
        return None

    metadata = {
        "dedup_key": row.get("dedup_key", ""),
        "title": row.get("title", ""),
        "url": row.get("url", ""),
        "factor_candidates": candidates,
    }
    assignment_block = "\n".join(assignments)
    metadata_literal = ascii(metadata)
    return f'''from __future__ import annotations

import numpy as np
import pandas as pd

FACTOR_METADATA = {metadata_literal}

fields = {json.dumps(output_fields, ensure_ascii=True)}


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


def _sum_cols(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    total = pd.Series(0.0, index=df.index, dtype="float64")
    for col in cols:
        total = total + _num(df, col)
    return total


def _safe_div(numer: pd.Series, denom: pd.Series) -> pd.Series:
    denom = denom.replace(0, np.nan)
    return (numer / denom).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _rolling_mean(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=max(1, int(window)), min_periods=1).mean()


def _rolling_sum(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=max(1, int(window)), min_periods=1).sum()


def _rolling_std(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=max(2, int(window)), min_periods=2).std().fillna(0.0)


def _pct_change(series: pd.Series, periods: int = 1) -> pd.Series:
    return series.pct_change(max(1, int(periods))).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _zscore(series: pd.Series, window: int = 20) -> pd.Series:
    mean = _rolling_mean(series, window)
    std = _rolling_std(series, window).replace(0, np.nan)
    return _safe_div(series - mean, std)


def _abs(series: pd.Series) -> pd.Series:
    return series.abs().replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _sign(series: pd.Series) -> pd.Series:
    return pd.Series(np.sign(series), index=series.index, dtype="float64").replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _log(series: pd.Series) -> pd.Series:
    return np.log(series.clip(lower=1e-12)).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _diff(series: pd.Series, periods: int = 1) -> pd.Series:
    return series.diff(max(1, int(periods))).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _ema(series: pd.Series, span: int = 20) -> pd.Series:
    return series.ewm(span=max(1, int(span)), adjust=False, min_periods=1).mean().replace([np.inf, -np.inf], np.nan).fillna(0.0)


def compute_factor(code: str, date: str, df: pd.DataFrame) -> pd.DataFrame:
    del code, date
    out = pd.DataFrame(index=df.index)
{assignment_block}
    return out.reset_index(drop=True)
'''


def write_generated_factor_files(rows: List[Dict[str, object]], generated_dir: Path) -> int:
    del rows, generated_dir
    count = 0
    return count


def load_factor_results(result_dir: Path) -> Dict[str, Dict[str, object]]:
    if not result_dir.exists():
        return {}
    results: Dict[str, Dict[str, object]] = {}
    for path in sorted(result_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        key = str(payload.get("dedup_key") or path.stem)
        if key:
            results[key] = payload
    return results


def attach_factor_results(rows: List[Dict[str, object]], results: Dict[str, Dict[str, object]]) -> None:
    for row in rows:
        dedup_key = str(row.get("dedup_key", ""))
        if dedup_key in results:
            row["factor_eval"] = results[dedup_key]


def _metric_mean(rows: List[Dict[str, object]], field: str) -> Optional[float]:
    values: List[float] = []
    for row in rows:
        value = row.get(field)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            values.append(float(value))
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _paper_hf_eval_row_summaries(field_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    eval_row_summaries: List[Dict[str, object]] = []
    for eval_row in field_rows:
        if not isinstance(eval_row, dict):
            continue
        eval_row_summaries.append(
            {
                "code": eval_row.get("code", ""),
                "horizon": eval_row.get("horizon", ""),
                "n_obs": eval_row.get("n_obs", ""),
                "daily_ic": eval_row.get("daily_ic"),
                "daily_rankic": eval_row.get("daily_rankic"),
                "global_ic": eval_row.get("global_ic"),
                "global_rankic": eval_row.get("global_rankic"),
                "qspread_mean": eval_row.get("qspread_mean"),
                "finite_ratio": eval_row.get("finite_ratio"),
                "zero_ratio": eval_row.get("zero_ratio"),
            }
        )
    return eval_row_summaries


def _paper_hf_eval_metric_payload(field_rows: List[Dict[str, object]]) -> Dict[str, object]:
    daily_values = [float(row.get("daily_ic")) for row in field_rows if isinstance(row.get("daily_ic"), (int, float))]
    field_summary = _factor_field_summary(field_rows)
    return {
        "mean_daily_ic": field_summary.get("mean_daily_ic"),
        "positive_ic_ratio": field_summary.get("positive_ic_ratio"),
        "mean_daily_rankic": field_summary.get("mean_daily_rankic"),
        "positive_rankic_ratio": field_summary.get("positive_rankic_ratio"),
        "mean_global_ic": field_summary.get("mean_global_ic"),
        "positive_global_ic_ratio": field_summary.get("positive_global_ic_ratio"),
        "mean_global_rankic": field_summary.get("mean_global_rankic"),
        "positive_global_rankic_ratio": field_summary.get("positive_global_rankic_ratio"),
        "mean_qspread": field_summary.get("mean_qspread"),
        "positive_qspread_ratio": field_summary.get("positive_qspread_ratio"),
        "mean_finite_ratio": field_summary.get("mean_finite_ratio"),
        "mean_zero_ratio": field_summary.get("mean_zero_ratio"),
        "total_obs": field_summary.get("total_obs"),
        "ic_gt_001_ratio": field_summary.get("ic_gt_001_ratio"),
        "ic_gt_002_ratio": field_summary.get("ic_gt_002_ratio"),
        "ic_gt_003_ratio": field_summary.get("ic_gt_003_ratio"),
        "abs_ic_gt_0015_ratio": field_summary.get("abs_ic_gt_0015_ratio"),
        "abs_ic_gt_002_ratio": field_summary.get("abs_ic_gt_002_ratio"),
        "positive_ic_count": sum(1 for value in daily_values if value > 0),
        "row_count": len(daily_values),
        "eval_rows": _paper_hf_eval_row_summaries(field_rows),
    }


def load_paper_hf_proxy_results(factor_dir: Path, result_dir: Path) -> Dict[Tuple[str, int], List[Dict[str, object]]]:
    manifest_path = factor_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    specs = manifest.get("specs", [])
    if not isinstance(specs, list):
        return {}
    result_path = result_dir / "paper_hf_direct_proxy_tests_v2.json"
    if not result_path.exists():
        result_path = result_dir / f"{Path(str(manifest.get('factor_file') or 'paper_hf_direct_proxy_tests_v2')).stem}.json"
    try:
        result_payload = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
    except Exception:
        result_payload = {}
    eval_rows = result_payload.get("rows", []) if isinstance(result_payload, dict) else []
    if not isinstance(eval_rows, list):
        eval_rows = []
    rows_by_field: Dict[str, List[Dict[str, object]]] = {}
    for row in eval_rows:
        if not isinstance(row, dict):
            continue
        field = str(row.get("factor_field") or "")
        if field:
            rows_by_field.setdefault(field, []).append(row)

    variants: Dict[Tuple[str, int], List[Dict[str, object]]] = {}
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        title = _normalize_text(str(spec.get("row_title") or ""))
        try:
            factor_index = int(spec.get("paper_hf_factor_index") or 0)
        except (TypeError, ValueError):
            factor_index = 0
        field = str(spec.get("field") or "")
        field_rows = rows_by_field.get(field, [])
        variant = {
            "field": field,
            "template": spec.get("template", ""),
            "formula": spec.get("formula", ""),
            "proxy_fidelity": spec.get("proxy_fidelity", ""),
            "proxy_loss": spec.get("proxy_loss", ""),
            "variant_index": spec.get("variant_index", 0),
            "generation_scope": spec.get("generation_scope", ""),
            "paper_hf_factor": spec.get("paper_hf_factor", {}),
            **_paper_hf_eval_metric_payload(field_rows),
        }
        variants.setdefault((title, factor_index), []).append(variant)
    return variants


def load_paper_hf_medium_results(promoted_dir: Path, result_dir: Path, fallback_result_path: Optional[Path] = None) -> Dict[str, Dict[str, object]]:
    metadata_path = promoted_dir / "paper_hf_relaxed_medium_candidates.json"
    result_path = result_dir / "paper_hf_relaxed_medium_candidates.json"
    if fallback_result_path is not None and fallback_result_path.exists():
        result_path = fallback_result_path
    if not result_path.exists():
        return {}
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    rows = result_payload.get("rows", []) if isinstance(result_payload, dict) else []
    if not isinstance(rows, list):
        rows = []
    rows_by_field: Dict[str, List[Dict[str, object]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        field = str(row.get("factor_field") or "")
        if field:
            rows_by_field.setdefault(field, []).append(row)
    factors = metadata.get("factors", []) if isinstance(metadata, dict) else []
    metadata_by_field = {
        str(item.get("field") or ""): item
        for item in factors
        if isinstance(item, dict) and str(item.get("field") or "")
    }
    medium_results: Dict[str, Dict[str, object]] = {}
    for field, field_rows in rows_by_field.items():
        item = metadata_by_field.get(field, {})
        payload = {
            "promoted_key": "paper_hf_relaxed_medium_candidates",
            "selection_score": item.get("selection_score"),
            "selection_reasons": item.get("selection_reasons", []),
            "template": item.get("template", ""),
            "proxy_fidelity": item.get("proxy_fidelity", ""),
            "proxy_loss": item.get("proxy_loss", ""),
            **_paper_hf_eval_metric_payload(field_rows),
        }
        medium_results[field] = payload
    return medium_results


def load_paper_hf_large_results(promoted_dir: Path, result_dir: Path) -> Dict[str, Dict[str, object]]:
    metadata_path = promoted_dir / "paper_hf_relaxed_medium_candidates.json"
    result_path = result_dir / "paper_hf_relaxed_medium_candidates.json"
    if not metadata_path.exists() or not result_path.exists():
        return {}
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    rows = result_payload.get("rows", []) if isinstance(result_payload, dict) else []
    if not isinstance(rows, list):
        rows = []
    rows_by_field: Dict[str, List[Dict[str, object]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        field = str(row.get("factor_field") or "")
        if field:
            rows_by_field.setdefault(field, []).append(row)
    factors = metadata.get("factors", []) if isinstance(metadata, dict) else []
    metadata_by_field = {
        str(item.get("field") or ""): item
        for item in factors
        if isinstance(item, dict) and str(item.get("field") or "")
    }
    large_results: Dict[str, Dict[str, object]] = {}
    for field, field_rows in rows_by_field.items():
        item = metadata_by_field.get(field, {})
        payload = {
            "promoted_key": "paper_hf_relaxed_medium_candidates",
            "selection_score": item.get("selection_score"),
            "selection_reasons": item.get("selection_reasons", []),
            "template": item.get("template", ""),
            "proxy_fidelity": item.get("proxy_fidelity", ""),
            "proxy_loss": item.get("proxy_loss", ""),
            **_paper_hf_eval_metric_payload(field_rows),
        }
        large_results[field] = payload
    return large_results


def attach_paper_hf_medium_results(rows: List[Dict[str, object]], medium_results: Dict[str, Dict[str, object]]) -> None:
    if not medium_results:
        return
    for row in rows:
        factors = row.get("paper_hf_factors") or row.get("hf_factor_points") or []
        if not isinstance(factors, list):
            continue
        for factor in factors:
            if not isinstance(factor, dict):
                continue
            variants = factor.get("proxy_variants_v2", [])
            if not isinstance(variants, list):
                continue
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                field = str(variant.get("field") or "")
                if field in medium_results:
                    variant["medium1_eval"] = medium_results[field]


def attach_paper_hf_large_results(rows: List[Dict[str, object]], large_results: Dict[str, Dict[str, object]]) -> None:
    if not large_results:
        return
    for row in rows:
        factors = row.get("paper_hf_factors") or row.get("hf_factor_points") or []
        if not isinstance(factors, list):
            continue
        for factor in factors:
            if not isinstance(factor, dict):
                continue
            variants = factor.get("proxy_variants_v2", [])
            if not isinstance(variants, list):
                continue
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                field = str(variant.get("field") or "")
                if field in large_results:
                    variant["large1_eval"] = large_results[field]


def _paper_hf_variant_dashboard(rows: List[Dict[str, object]]) -> Dict[str, object]:
    factors_total = 0
    formula_ready_total = 0
    formula_ready_ids: set[str] = set()
    known_factor_ids: set[str] = set()
    manifest_factor_keys: set[Tuple[str, str]] = set()
    manifest_path = DEFAULT_PROXY_REGISTRY_PATH.parents[1] / "data" / "paper_hf_factor_tests_v2" / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        for spec in manifest.get("specs", []) if isinstance(manifest, dict) else []:
            if not isinstance(spec, dict) or not spec.get("field"):
                continue
            row_key = str(spec.get("row_url") or spec.get("row_title") or "")
            raw_index = spec.get("paper_hf_factor_index")
            if row_key and raw_index is not None:
                manifest_factor_keys.add((row_key, str(raw_index)))
    mechanisms_with_v2 = 0
    small_by_paper_factor: Dict[Tuple[str, str], Dict[str, object]] = {}
    medium_by_paper_factor: Dict[Tuple[str, str], Dict[str, object]] = {}
    large_by_paper_factor: Dict[Tuple[str, str], Dict[str, object]] = {}
    for row_index, row in enumerate(rows):
        row_key = str(row.get("url") or row.get("title") or "")
        dedup_key = str(row.get("dedup_key") or f"row_{row_index}")
        factors = _strict_paper_hf_factors_for_row(row)
        factors_total += len(factors)
        for factor_index, factor in enumerate(factors):
            if not isinstance(factor, dict):
                continue
            hf_factor_id = f"{dedup_key}:{factor_index}"
            known_factor_ids.add(hf_factor_id)
            plan = factor.get("paper_hf_formula_plan") if isinstance(factor.get("paper_hf_formula_plan"), dict) else {}
            has_custom_formula = bool(str(plan.get("custom_formula") or "").strip()) and not factor.get("is_placeholder")
            if has_custom_formula:
                formula_ready_total += 1
                formula_ready_ids.add(hf_factor_id)
            if has_custom_formula and ((row_key, str(factor_index)) in manifest_factor_keys or not manifest_factor_keys):
                mechanisms_with_v2 += 1
            variants = factor.get("proxy_variants_v2", [])
            if not isinstance(variants, list) or not variants:
                continue
            paper_factor_key = (row_key, str(factor_index))
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                field = str(variant.get("field") or "")
                if not field:
                    continue
                _keep_best_proxy_variant(small_by_paper_factor, paper_factor_key, variant)
                medium_eval = variant.get("medium1_eval")
                if isinstance(medium_eval, dict):
                    medium_candidate = {**variant, **medium_eval, "field": field, "template": variant.get("template")}
                    _keep_best_proxy_variant(medium_by_paper_factor, paper_factor_key, medium_candidate)
                large_eval = variant.get("large1_eval")
                if isinstance(large_eval, dict):
                    large_candidate = {**variant, **large_eval, "field": field, "template": variant.get("template")}
                    _keep_best_proxy_variant(large_by_paper_factor, paper_factor_key, large_candidate)

        attempted_ids: set[str] = set()
        bulk_state_path = DEFAULT_PROXY_REGISTRY_PATH.parents[1] / "data" / "bulk_composite_factor_synthesis_state.json"
        if bulk_state_path.exists():
            try:
                bulk_state = json.loads(bulk_state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                bulk_state = {}
            if isinstance(bulk_state, dict):
                attempted_ids = {str(item) for item in bulk_state.get("attempted_missing_formula_hf_factor_ids", []) if str(item)} & known_factor_ids
        baseline_formula_ready = formula_ready_total
        if bulk_state_path.exists():
            try:
                baseline_formula_ready = int(bulk_state.get("formula_ready_baseline", formula_ready_total)) if isinstance(bulk_state, dict) else formula_ready_total
            except (TypeError, ValueError):
                baseline_formula_ready = formula_ready_total
        formula_coverage_total = baseline_formula_ready + len(attempted_ids)

    def metric_summary(items: Dict[str, Dict[str, object]]) -> Dict[str, object]:
        ic_values = [_variant_small_ic_for_horizon(item) for item in items.values()]
        rankic_values = [_variant_metric_for_horizon(item, "daily_rankic", "mean_daily_rankic") for item in items.values()]
        qspread_values = [_variant_metric_for_horizon(item, "qspread_mean", "mean_qspread") for item in items.values()]
        finite_values = [_variant_metric_for_horizon(item, "finite_ratio", "mean_finite_ratio") for item in items.values()]
        zero_values = [_variant_metric_for_horizon(item, "zero_ratio", "mean_zero_ratio") for item in items.values()]
        ic_values = [value for value in ic_values if value is not None]
        rankic_values = [value for value in rankic_values if value is not None]
        qspread_values = [value for value in qspread_values if value is not None]
        finite_values = [value for value in finite_values if value is not None]
        zero_values = [value for value in zero_values if value is not None]

        def mean(values: List[float]) -> Optional[float]:
            return round(sum(values) / len(values), 6) if values else None

        def pos(values: List[float]) -> Optional[float]:
            return (sum(1 for value in values if value > 0) / len(values)) if values else None

        def threshold_payload(thresholds: Tuple[float, ...], absolute: bool = False) -> List[Dict[str, object]]:
            payload = []
            for threshold in thresholds:
                count = sum(1 for value in ic_values if (abs(value) if absolute else value) > threshold)
                ratio = (count / len(ic_values)) if ic_values else None
                payload.append({"threshold": threshold, "count": count, "ratio": ratio})
            return payload

        interval_counts: Dict[str, int] = {}
        for value in ic_values:
            bucket = _factor_ic_bucket(abs(value))
            if bucket:
                interval_counts[bucket] = interval_counts.get(bucket, 0) + 1
        interval_payload = [
            {
                "bucket": bucket,
                "lower": float(bucket.split("-", 1)[0]),
                "count": count,
                "ratio": (count / len(ic_values)) if ic_values else None,
            }
            for bucket, count in sorted(interval_counts.items(), key=lambda item: float(item[0].split("-", 1)[0]))
        ]

        return {
            "field_count": len(items),
            "ic_sample_count": len(ic_values),
            "mean_ic": mean(ic_values),
            "positive_ic_ratio": pos(ic_values),
            "mean_rankic": mean(rankic_values),
            "positive_rankic_ratio": pos(rankic_values),
            "mean_qspread": mean(qspread_values),
            "positive_qspread_ratio": pos(qspread_values),
            "mean_finite_ratio": mean(finite_values),
            "mean_zero_ratio": mean(zero_values),
            "ic_gt_001_ratio": (sum(1 for value in ic_values if value > 0.01) / len(ic_values)) if ic_values else None,
            "ic_gt_002_ratio": (sum(1 for value in ic_values if value > 0.02) / len(ic_values)) if ic_values else None,
            "ic_gt_003_ratio": (sum(1 for value in ic_values if value > 0.03) / len(ic_values)) if ic_values else None,
            "abs_ic_gt_0015_ratio": (sum(1 for value in ic_values if abs(value) > 0.015) / len(ic_values)) if ic_values else None,
            "abs_ic_gt_002_ratio": (sum(1 for value in ic_values if abs(value) > 0.02) / len(ic_values)) if ic_values else None,
            "positive_thresholds": threshold_payload((0.01, 0.02, 0.03), absolute=False),
            "absolute_thresholds": threshold_payload((0.015, 0.02), absolute=True),
            "absolute_ic_intervals": interval_payload,
        }

    return {
        "paper_hf_factor_count": factors_total,
        "formula_ready_paper_hf_factor_count": formula_ready_total,
        "formula_coverage_paper_hf_factor_count": formula_coverage_total,
        "formula_ready_baseline_paper_hf_factor_count": baseline_formula_ready,
        "bulk_composite_tested_paper_hf_factor_count": len(attempted_ids),
        "mechanisms_with_v2": mechanisms_with_v2,
        "small": metric_summary(small_by_paper_factor),
        "medium": metric_summary(medium_by_paper_factor),
        "large": metric_summary(large_by_paper_factor),
    }


def attach_paper_hf_proxy_results(rows: List[Dict[str, object]], variants: Dict[Tuple[str, int], List[Dict[str, object]]]) -> None:
    if not variants:
        return
    for row in rows:
        title = _normalize_text(str(row.get("title") or ""))
        factors = row.get("paper_hf_factors") or row.get("hf_factor_points") or []
        if not isinstance(factors, list):
            continue
        for index, factor in enumerate(factors):
            if not isinstance(factor, dict):
                continue
            matched = variants.get((title, index), [])
            if matched:
                factor["proxy_variants_v2"] = matched
                manifest_factor = matched[0].get("paper_hf_factor") if isinstance(matched[0], dict) else None
                if isinstance(manifest_factor, dict):
                    for key in ("proxy_mappings", "proxy_status", "proxy_status_reason", "unresolved_proxy_variables"):
                        value = manifest_factor.get(key)
                        if value:
                            factor[key] = value


def load_factor_quality_results(report_path: Path) -> Dict[str, Dict[str, Dict[str, object]]]:
    if not report_path.exists():
        return {}
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, list):
        return {}

    results: Dict[str, Dict[str, Dict[str, object]]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        dedup_key = str(item.get("dedup_key", ""))
        factor_field = str(item.get("factor_field", ""))
        if not dedup_key or not factor_field:
            continue
        results.setdefault(dedup_key, {})[factor_field] = item
    return results


def attach_factor_quality_results(rows: List[Dict[str, object]], results: Dict[str, Dict[str, Dict[str, object]]]) -> None:
    for row in rows:
        dedup_key = str(row.get("dedup_key", ""))
        if dedup_key in results:
            row["factor_quality"] = results[dedup_key]


def load_promoted_factor_results(promoted_dir: Path, result_dir: Path) -> Dict[str, Dict[str, Dict[str, object]]]:
    if not promoted_dir.exists() or not result_dir.exists():
        return {}
    results: Dict[str, Dict[str, Dict[str, object]]] = {}
    for meta_path in sorted(promoted_dir.glob("*.json")):
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(metadata, dict):
            continue
        source_key = str(metadata.get("source_dedup_key", ""))
        factor_field = str(metadata.get("factor_field", ""))
        promoted_key = str(metadata.get("promoted_key") or meta_path.stem)
        if not source_key or not factor_field or not promoted_key:
            continue
        result_path = result_dir / f"{promoted_key}.json"
        if not result_path.exists():
            continue
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            results.setdefault(source_key, {})[factor_field] = payload
    return results


def attach_promoted_factor_results(rows: List[Dict[str, object]], field_name: str, results: Dict[str, Dict[str, Dict[str, object]]]) -> None:
    for row in rows:
        dedup_key = str(row.get("dedup_key", ""))
        if dedup_key in results:
            row[field_name] = results[dedup_key]


def _metric_float(value: object) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:
        return None
    return numeric


def _parse_row_datetime(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dashboard_summary(rows: List[Dict[str, object]]) -> Dict[str, object]:
    article_count = len(rows)
    scores = [_metric_float(row.get("recommendation_score")) for row in rows]
    scores = [score for score in scores if score is not None]
    schema_v6 = sum(1 for row in rows if "schema-v6" in str(row.get("analysis_agent", "")))
    schema_v2 = sum(1 for row in rows if str(row.get("analysis_version", "")) == "v2")
    publish_times = [_parse_row_datetime(row.get("publish_time")) for row in rows]
    publish_times = [ptime for ptime in publish_times if ptime is not None]
    latest_publish_time = max(publish_times) if publish_times else None
    recent_7d_count = 0
    if latest_publish_time is not None:
        recent_7d_count = sum(1 for ptime in publish_times if (latest_publish_time - ptime).days < 7)
    paper_factor_count = sum(len(_strict_paper_hf_factors_for_row(row)) for row in rows)
    paper_hf_dashboard = _paper_hf_variant_dashboard(rows)

    return {
        "article_count": article_count,
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "schema_v6": schema_v6,
        "schema_v6_ratio": (schema_v6 / article_count) if article_count else None,
        "schema_v2": schema_v2,
        "schema_v2_ratio": (schema_v2 / article_count) if article_count else None,
        "recent_7d_count": recent_7d_count,
        "paper_factor_count": paper_factor_count,
        "paper_hf_dashboard": paper_hf_dashboard,
    }


def _ratio_text(count: int, ratio: object) -> str:
    if ratio is None:
        return f"{count} / 0"
    return f"{count} / {round(float(ratio) * 100, 1)}%"


def _dashboard_html(rows: List[Dict[str, object]]) -> str:
    summary = _dashboard_summary(rows)
    avg_score = "NA" if summary["avg_score"] is None else str(summary["avg_score"])
    v2_ratio = "NA" if summary["schema_v2_ratio"] is None else f'{float(summary["schema_v2_ratio"]) * 100:.1f}%'
    v6_ratio = "NA" if summary["schema_v6_ratio"] is None else f'{float(summary["schema_v6_ratio"]) * 100:.1f}%'
    paper_hf_dashboard = summary.get("paper_hf_dashboard", {}) if isinstance(summary.get("paper_hf_dashboard"), dict) else {}
    paper_hf_small = paper_hf_dashboard.get("small", {}) if isinstance(paper_hf_dashboard.get("small"), dict) else {}
    paper_hf_medium = paper_hf_dashboard.get("medium", {}) if isinstance(paper_hf_dashboard.get("medium"), dict) else {}
    paper_hf_large = paper_hf_dashboard.get("large", {}) if isinstance(paper_hf_dashboard.get("large"), dict) else {}
    phf_small_ic = "NA" if paper_hf_small.get("mean_ic") is None else f'{float(paper_hf_small["mean_ic"]):.4f}'
    phf_small_ic_pos = "NA" if paper_hf_small.get("positive_ic_ratio") is None else f'{float(paper_hf_small["positive_ic_ratio"]) * 100:.1f}%'
    phf_small_rankic_pos = "NA" if paper_hf_small.get("positive_rankic_ratio") is None else f'{float(paper_hf_small["positive_rankic_ratio"]) * 100:.1f}%'
    phf_small_qspread_pos = "NA" if paper_hf_small.get("positive_qspread_ratio") is None else f'{float(paper_hf_small["positive_qspread_ratio"]) * 100:.1f}%'
    phf_small_finite = "NA" if paper_hf_small.get("mean_finite_ratio") is None else f'{float(paper_hf_small["mean_finite_ratio"]) * 100:.1f}%'
    phf_medium_ic = "NA" if paper_hf_medium.get("mean_ic") is None else f'{float(paper_hf_medium["mean_ic"]):.4f}'
    phf_medium_ic_pos = "NA" if paper_hf_medium.get("positive_ic_ratio") is None else f'{float(paper_hf_medium["positive_ic_ratio"]) * 100:.1f}%'
    phf_medium_rankic_pos = "NA" if paper_hf_medium.get("positive_rankic_ratio") is None else f'{float(paper_hf_medium["positive_rankic_ratio"]) * 100:.1f}%'
    phf_medium_qspread_pos = "NA" if paper_hf_medium.get("positive_qspread_ratio") is None else f'{float(paper_hf_medium["positive_qspread_ratio"]) * 100:.1f}%'
    phf_medium_finite = "NA" if paper_hf_medium.get("mean_finite_ratio") is None else f'{float(paper_hf_medium["mean_finite_ratio"]) * 100:.1f}%'
    phf_large_ic = "NA" if paper_hf_large.get("mean_ic") is None else f'{float(paper_hf_large["mean_ic"]):.4f}'
    phf_large_ic_pos = "NA" if paper_hf_large.get("positive_ic_ratio") is None else f'{float(paper_hf_large["positive_ic_ratio"]) * 100:.1f}%'
    phf_large_rankic_pos = "NA" if paper_hf_large.get("positive_rankic_ratio") is None else f'{float(paper_hf_large["positive_rankic_ratio"]) * 100:.1f}%'
    phf_large_qspread_pos = "NA" if paper_hf_large.get("positive_qspread_ratio") is None else f'{float(paper_hf_large["positive_qspread_ratio"]) * 100:.1f}%'
    phf_large_finite = "NA" if paper_hf_large.get("mean_finite_ratio") is None else f'{float(paper_hf_large["mean_finite_ratio"]) * 100:.1f}%'
    medium_cards = ""
    if int(paper_hf_medium.get("field_count") or 0) > 0:
        medium_cards = (
            f'<div class="stat-card"><div class="stat-label">HF Medium复检</div><div class="stat-value">{int(paper_hf_medium.get("field_count", 0))}</div><div class="stat-sub">Mean IC {html.escape(phf_medium_ic)} | IC&gt;0 {html.escape(phf_medium_ic_pos)}</div></div>'
            f'<div class="stat-card"><div class="stat-label">HF Medium方向</div><div class="stat-value">{html.escape(phf_medium_rankic_pos)}</div><div class="stat-sub">RankIC&gt;0 | QSpread&gt;0 {html.escape(phf_medium_qspread_pos)} | Finite {html.escape(phf_medium_finite)}</div></div>'
        )
    large_cards = ""
    if int(paper_hf_large.get("field_count") or 0) > 0:
        large_cards = (
            f'<div class="stat-card"><div class="stat-label">HF Large复检</div><div class="stat-value">{int(paper_hf_large.get("field_count", 0))}</div><div class="stat-sub">Mean IC {html.escape(phf_large_ic)} | IC&gt;0 {html.escape(phf_large_ic_pos)}</div></div>'
            f'<div class="stat-card"><div class="stat-label">HF Large方向</div><div class="stat-value">{html.escape(phf_large_rankic_pos)}</div><div class="stat-sub">RankIC&gt;0 | QSpread&gt;0 {html.escape(phf_large_qspread_pos)} | Finite {html.escape(phf_large_finite)}</div></div>'
        )

    def hf_threshold_grid(title: str, payload: Dict[str, object]) -> str:
        if not payload or int(payload.get("field_count") or 0) == 0:
            return ""
        cards: List[str] = []
        for item in payload.get("positive_thresholds", []):
            if not isinstance(item, dict):
                continue
            cards.append(
                f'<div class="threshold-card"><strong>{html.escape(title)} IC &gt; {float(item["threshold"]):.3f}</strong><span>{_ratio_text(int(item["count"]), item["ratio"])}</span></div>'
            )
        for item in payload.get("absolute_thresholds", []):
            if not isinstance(item, dict):
                continue
            cards.append(
                f'<div class="threshold-card"><strong>{html.escape(title)} |IC| &gt; {float(item["threshold"]):.3f}</strong><span>{_ratio_text(int(item["count"]), item["ratio"])}</span></div>'
            )
        if not cards:
            return ""
        return f'<div class="dashboard-note">{html.escape(title)} IC分布</div><div class="threshold-grid">{"".join(cards)}</div>'

    hf_threshold_sections = "".join(
        [
            hf_threshold_grid("HF V2 Small", paper_hf_small),
            hf_threshold_grid("HF Medium", paper_hf_medium),
            hf_threshold_grid("HF Large", paper_hf_large),
        ]
    )
    small_ic_intervals = paper_hf_small.get("absolute_ic_intervals", []) if isinstance(paper_hf_small, dict) else []
    interval_cards: List[str] = []
    interval_options = ['<option value="all">全部 IC 区间</option>']
    if isinstance(small_ic_intervals, list):
        for item in sorted(
            [value for value in small_ic_intervals if isinstance(value, dict)],
            key=lambda value: float(value.get("lower") or 0),
            reverse=True,
        ):
            bucket = html.escape(str(item.get("bucket") or ""))
            if not bucket:
                continue
            count = int(item.get("count") or 0)
            ratio = item.get("ratio")
            ratio_text = "NA" if ratio is None else f"{float(ratio) * 100:.1f}%"
            label = f"|IC| {bucket}"
            interval_options.append(f'<option value="{bucket}">{html.escape(label)} ({count})</option>')
            interval_cards.append(
                f'<button class="threshold-card ic-interval-card" type="button" data-factor-ic-bucket="{bucket}">'
                f'<strong>{html.escape(label)}</strong><span>{count}</span><em>{html.escape(ratio_text)} · 点击检索</em></button>'
            )
    interval_section = ""
    if interval_cards:
        interval_sample_count = int(paper_hf_small.get("ic_sample_count") or 0)
        interval_total_count = int(paper_hf_dashboard.get("mechanisms_with_v2") or 0)
        interval_section = (
            f'<div class="dashboard-note">HF V2 Small 60s |IC| 区间统计（每个原始因子取最佳代理；步长 0.01；百分比分母为当前有 small 60s IC 的 {interval_sample_count} 个原始因子，不是全部 {interval_total_count} 个已生成代理；点击区间后按 |IC| 降序列文章）</div>'
            f'<div class="threshold-grid">{"".join(interval_cards)}</div>'
        )
    interval_options_html = "".join(interval_options)
    return f'''
  <section class="dashboard" id="digest-dashboard">
    <div class="dashboard-head">
      <div>
        <h2>论文生成因子仪表盘</h2>
                <div class="dashboard-note">当前主路径为 <code>paper_hf_factors</code> → proxy registry → HF V2 deterministic variants；统计口径为每个原始因子取最佳代理。</div>
      </div>
            <div class="dashboard-note" id="dashboard-result-count">显示 {int(summary["article_count"])} / {int(summary["article_count"])} 篇</div>
    </div>
    <div class="stat-grid">
      <div class="stat-card"><div class="stat-label">文章数</div><div class="stat-value">{int(summary["article_count"])}</div><div class="stat-sub">schema-v6 {int(summary["schema_v6"])} 篇</div></div>
    <div class="stat-card"><div class="stat-label">近 7 天新增</div><div class="stat-value">{int(summary["recent_7d_count"])}</div><div class="stat-sub">以本页最新发布日期为锚点</div></div>
        <div class="stat-card"><div class="stat-label">v6 解析比例</div><div class="stat-value">{html.escape(v6_ratio)}</div><div class="stat-sub">{int(summary["schema_v6"])} / {int(summary["article_count"])} 篇</div></div>
        <div class="stat-card"><div class="stat-label">v2 解析比例</div><div class="stat-value">{html.escape(v2_ratio)}</div><div class="stat-sub">{int(summary["schema_v2"])} / {int(summary["article_count"])} 篇</div></div>
      <div class="stat-card"><div class="stat-label">平均推荐分</div><div class="stat-value">{html.escape(avg_score)}</div><div class="stat-sub">当前页面文章均值</div></div>
    <div class="stat-card"><div class="stat-label">明确公式 HF</div><div class="stat-value">{int(paper_hf_dashboard.get("formula_ready_paper_hf_factor_count", 0))}</div><div class="stat-sub">严格来自 paper_hf_formula_plan.custom_formula</div></div>
    <div class="stat-card"><div class="stat-label">明确公式代理覆盖</div><div class="stat-value">{int(paper_hf_dashboard.get("mechanisms_with_v2", 0))} / {int(paper_hf_dashboard.get("formula_ready_paper_hf_factor_count", paper_hf_dashboard.get("paper_hf_factor_count", 0)))}</div><div class="stat-sub">LLM 已测试 {int(paper_hf_dashboard.get("bulk_composite_tested_paper_hf_factor_count", 0))}；small 有 IC 样本 {int(paper_hf_small.get("ic_sample_count", 0))} 个</div></div>
    <div class="stat-card"><div class="stat-label">HF V2 Small</div><div class="stat-value">{html.escape(phf_small_ic)}</div><div class="stat-sub">IC&gt;0 {html.escape(phf_small_ic_pos)} | Finite {html.escape(phf_small_finite)}</div></div>
    <div class="stat-card"><div class="stat-label">HF V2 Small方向</div><div class="stat-value">{html.escape(phf_small_rankic_pos)}</div><div class="stat-sub">RankIC&gt;0 | QSpread&gt;0 {html.escape(phf_small_qspread_pos)}</div></div>
    {medium_cards}{large_cards}
    </div>
        {hf_threshold_sections}
    {interval_section}
        <!-- HF_PROXY_DIVERSITY_SUMMARY_START -->
        <!-- HF_PROXY_DIVERSITY_SUMMARY_END -->
        <div class="paper-search" aria-label="Paper search">
            <div class="paper-search-title">Paper Digest<span>search / filter / rank</span></div>
            <div class="search-row">
                <button class="search-icon" id="digest-search-focus" type="button" aria-label="聚焦搜索框">🔎</button>
                <input id="digest-search" type="search" placeholder="搜索标题 / 关键词 / 因子名 / 摘要…">
            </div>
            <div class="search-tabs" role="group" aria-label="搜索模式">
                <button class="search-tab active" type="button" data-search-mode="all">全部</button>
                <button class="search-tab" type="button" data-search-mode="today">今日</button>
                <button class="search-tab" type="button" data-search-mode="tag">按 Tag</button>
                <button class="search-tab" type="button" data-search-mode="source">按源</button>
            </div>
        </div>
    <div class="controls">
      <select id="digest-filter">
        <option value="all">全部文章</option>
        <option value="schema-v6">仅 schema-v6</option>
        <option value="has-factors">有论文高频因子</option>
        <option value="has-candidates">有 HF V2 代理</option>
      </select>
            <select id="factor-ic-filter">
                {interval_options_html}
            </select>
      <select id="digest-sort">
        <option value="date-desc">日期↓</option>
                <option value="factor-abs-ic-desc">60s |IC|↓</option>
        <option value="score-desc">评分↓</option>
        <option value="factor-desc">HF 因子数↓</option>
        <option value="title-asc">标题↑</option>
      </select>
    </div>
  </section>
'''


def _dashboard_script() -> str:
    return """
<script>
(function(){
  const cards = Array.from(document.querySelectorAll('.digest-card'));
  const search = document.getElementById('digest-search');
    const searchFocus = document.getElementById('digest-search-focus');
  const filter = document.getElementById('digest-filter');
    const factorIcFilter = document.getElementById('factor-ic-filter');
  const sort = document.getElementById('digest-sort');
  const count = document.getElementById('dashboard-result-count');
  const list = document.getElementById('digest-card-list');
    const tabs = Array.from(document.querySelectorAll('.search-tab'));
        const intervalCards = Array.from(document.querySelectorAll('.ic-interval-card'));
  if (!cards.length || !search || !filter || !sort || !list) return;
    const latestDay = cards.map(card => card.dataset.day || '').sort().pop() || '';
    let searchMode = 'all';
        const defaultLimit = 10;
  function number(card, name, fallback){
    const value = Number(card.dataset[name]);
    return Number.isFinite(value) ? value : fallback;
  }
    function searchTarget(card){
        if (searchMode === 'tag') return card.dataset.tags || '';
        if (searchMode === 'source') return card.dataset.source || '';
        return card.dataset.search || '';
    }
  function passes(card){
    const q = search.value.trim().toLowerCase();
    const mode = filter.value;
        const icBucket = factorIcFilter ? factorIcFilter.value : 'all';
        if (searchMode === 'today' && card.dataset.day !== latestDay) return false;
        if (q && !searchTarget(card).includes(q)) return false;
    if (mode === 'schema-v6' && card.dataset.schema !== 'schema-v6') return false;
    if (mode === 'has-factors' && number(card, 'paperFactors', 0) <= 0) return false;
    if (mode === 'has-candidates' && number(card, 'proxyFactors', 0) <= 0) return false;
        if (icBucket !== 'all' && card.dataset.factorIcBucket !== icBucket) return false;
    return true;
  }
  function compare(a,b){
    const mode = sort.value;
        if (mode === 'factor-abs-ic-desc') return number(b, 'factorAbsIc', -1) - number(a, 'factorAbsIc', -1);
    if (mode === 'score-desc') return number(b, 'score', -1) - number(a, 'score', -1);
    if (mode === 'factor-desc') return number(b, 'paperFactors', 0) - number(a, 'paperFactors', 0);
    if (mode === 'title-asc') return (a.dataset.title || '').localeCompare(b.dataset.title || '');
    return (b.dataset.date || '').localeCompare(a.dataset.date || '');
  }
    function hasActiveControls(){
        const icBucket = factorIcFilter ? factorIcFilter.value : 'all';
        return Boolean(search.value.trim()) || filter.value !== 'all' || searchMode !== 'all' || icBucket !== 'all' || sort.value !== 'date-desc';
    }
  function apply(){
        const filtered = cards.filter(passes).sort(compare);
        const visible = hasActiveControls() ? filtered : filtered.slice(0, defaultLimit);
    cards.forEach(card => card.style.display = 'none');
    visible.forEach(card => { card.style.display = ''; list.appendChild(card); });
        intervalCards.forEach(card => card.classList.toggle('active', factorIcFilter && factorIcFilter.value === card.dataset.factorIcBucket));
        if (count) count.textContent = '显示 ' + visible.length + ' / ' + cards.length + ' 篇' + (hasActiveControls() ? '' : '（默认最近10篇）');
  }
  search.addEventListener('input', apply);
    if (searchFocus) searchFocus.addEventListener('click', function(){ search.focus(); search.select(); });
  filter.addEventListener('change', apply);
    if (factorIcFilter) factorIcFilter.addEventListener('change', function(){ if (this.value !== 'all') sort.value = 'factor-abs-ic-desc'; apply(); });
  sort.addEventListener('change', apply);
        intervalCards.forEach(card => card.addEventListener('click', function(){
                if (!factorIcFilter) return;
                factorIcFilter.value = this.dataset.factorIcBucket || 'all';
                sort.value = 'factor-abs-ic-desc';
                apply();
        }));
    tabs.forEach(tab => tab.addEventListener('click', function(){
        searchMode = this.dataset.searchMode || 'all';
        tabs.forEach(item => item.classList.toggle('active', item === this));
        apply();
    }));
  apply();
})();
</script>
"""


def _article_cards(rows: List[Dict[str, object]]) -> str:
    cards: List[str] = []
    for r in rows:
        title = html.escape(str(r.get("title", "")))
        url = html.escape(str(r.get("url", "")))
        summary = html.escape(str(r.get("summary", "")))
        source = html.escape(str(r.get("source_name", "")))
        ptime = html.escape(str(r.get("publish_time", "")))
        tags = ", ".join(str(x) for x in r.get("tags", []))
        tags = html.escape(tags)
        core_idea = html.escape(str(r.get("core_idea", "")))
        factor_html = _factor_candidate_cards(r)
        factor_values_html = ""
        raw_analysis_agent = str(r.get("analysis_agent", "")) or "analysis"
        analysis_agent = html.escape(raw_analysis_agent)
        analysis_title = "LLM 解读" if "paper-llm-agent" in analysis_agent else "规则解读"
        score = _format_score(r.get("recommendation_score", 0))
        score_value = _metric_float(r.get("recommendation_score")) or 0.0
        best_proxy_variant = _best_proxy_variant_summary(r)
        best_proxy_ic = _variant_small_ic_for_horizon(best_proxy_variant) if isinstance(best_proxy_variant, dict) else None
        best_proxy_abs_ic = abs(best_proxy_ic) if best_proxy_ic is not None else None
        best_proxy_bucket = _factor_ic_bucket(best_proxy_abs_ic)
        best_proxy_field = str(best_proxy_variant.get("field") or "") if isinstance(best_proxy_variant, dict) else ""
        proxy_backtest_badge = _proxy_backtest_badge(r, score_value)
        paper_factors = _paper_factors_for_row(r)
        paper_factor_count = len(paper_factors)
        proxy_factor_count = sum(
            1
            for factor in paper_factors
            if isinstance(factor.get("proxy_variants_v2", []), list) and factor.get("proxy_variants_v2", [])
        )
        schema_label = "schema-v6" if "schema-v6" in raw_analysis_agent else "other"
        search_text = " ".join(
            [
                str(r.get("title", "")),
                str(r.get("summary", "")),
                str(r.get("core_idea", "")),
                str(r.get("analysis_summary", "")),
                str(r.get("source_name", "")),
                " ".join(str(x) for x in r.get("tags", [])),
                " ".join(str(factor.get("name", "")) for factor in paper_factors),
                " ".join(str(factor.get("mechanism_formula", "")) for factor in paper_factors),
                " ".join(str(factor.get("meaning", "")) for factor in paper_factors),
                " ".join(str(factor.get("paper_mechanism", "")) for factor in paper_factors),
                " ".join(str(factor.get("procedure", "")) for factor in paper_factors),
                " ".join(str(factor.get("rationale", "")) for factor in paper_factors),
                " ".join(", ".join(str(field) for field in factor.get("ideal_input_fields", []) if str(field).strip()) for factor in paper_factors if isinstance(factor.get("ideal_input_fields", []), list)),
                " ".join(str(variant.get("field", "")) for factor in paper_factors for variant in (factor.get("proxy_variants_v2", []) if isinstance(factor.get("proxy_variants_v2", []), list) else []) if isinstance(variant, dict)),
                " ".join(str(variant.get("formula", "")) for factor in paper_factors for variant in (factor.get("proxy_variants_v2", []) if isinstance(factor.get("proxy_variants_v2", []), list) else []) if isinstance(variant, dict)),
                " ".join(str(variant.get("template", "")) for factor in paper_factors for variant in (factor.get("proxy_variants_v2", []) if isinstance(factor.get("proxy_variants_v2", []), list) else []) if isinstance(variant, dict)),
            ]
        ).lower()
        title_attr = html.escape(str(r.get("title", "")).lower())
        date_attr = html.escape(str(r.get("publish_time", "")))
        day_attr = html.escape(str(r.get("publish_time", ""))[:10])
        source_attr = html.escape(str(r.get("source_name", "")).lower())
        tags_attr = html.escape(" ".join(str(x) for x in r.get("tags", [])).lower())
        search_attr = html.escape(search_text)
        factor_ic_attr = "" if best_proxy_ic is None else f"{best_proxy_ic:.6f}"
        factor_abs_ic_attr = "" if best_proxy_abs_ic is None else f"{best_proxy_abs_ic:.6f}"
        factor_bucket_attr = html.escape(best_proxy_bucket)
        factor_field_attr = html.escape(best_proxy_field)
        score_dimensions = _normalize_dimension_scores(r.get("score_dimensions", {}))
        dim_html = "".join(
            f'<div class="dim-card"><div class="dim-head"><span>{html.escape(v["label"])}</span>'
            f'<span>{_format_score(v["score"])}/10</span></div>'
            f'<div class="dim-desc">{html.escape(str(v["comment"]))}</div>'
            f'<div class="dim-evidence">证据：{html.escape(str(v.get("evidence", "") or "摘要未披露"))}</div>'
            f'<div class="dim-evidence">批判：{html.escape(str(v.get("critique", "") or "待补充扣分理由"))}</div></div>'
            for v in score_dimensions.values()
        )
        structured_summary_html = _structured_summary_html(r.get("structured_summary", {}))
        cards.append(
            f"""
<article class="card digest-card" data-title="{title_attr}" data-date="{date_attr}" data-day="{day_attr}" data-source="{source_attr}" data-tags="{tags_attr}" data-score="{score_value:.6f}" data-schema="{schema_label}" data-paper-factors="{paper_factor_count}" data-proxy-factors="{proxy_factor_count}" data-factor-ic="{factor_ic_attr}" data-factor-abs-ic="{factor_abs_ic_attr}" data-factor-ic-bucket="{factor_bucket_attr}" data-factor-field="{factor_field_attr}" data-factor-horizon="ret60s" data-search="{search_attr}">
  <h3><a href="{url}" target="_blank">{title}</a></h3>
  <div class="meta">{source} | {ptime} | <span class="tags">{tags}</span></div>
    <div><span class="score">文章质量分: {score}/10</span>{proxy_backtest_badge}</div>
    {structured_summary_html}
        <section class="read-section"><h4 class="read-section-title">维度评分</h4><div class="dim-grid">{dim_html}</div></section>
    <section class="llm-section">
        <div class="section-title">{analysis_title}<span>{analysis_agent}</span></div>
        <p><strong>文章核心idea：</strong>{core_idea}</p>
        {factor_html}
    </section>
                {factor_values_html}
  <p><strong>摘要：</strong>{summary}</p>
</article>
"""
        )
    return "\n".join(cards) if cards else "<p class='muted'>暂无匹配文章。</p>"


def build_history(data_dir: Path) -> List[Dict[str, object]]:
    days: List[Dict[str, object]] = []
    for p in sorted(data_dir.glob("daily_*.jsonl"), reverse=True):
        day = p.stem.replace("daily_", "")
        rows = read_jsonl(p)
        days.append(
            {
                "day": day,
                "count": len(rows),
                "html_file": f"daily_{day}.html",
            }
        )
    return days


def _paper_factor_items(row: Dict[str, object]) -> List[Dict[str, object]]:
    raw = row.get("paper_hf_factors") or row.get("hf_factor_points") or []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _row_has_real_formula(row: Dict[str, object]) -> bool:
    for item in _paper_factor_items(row):
        formula = _normalize_text(str(item.get("mechanism_formula") or item.get("formula") or ""))
        if formula and "待 LLM" not in formula and "待LLM" not in formula and not item.get("is_placeholder"):
            return True
    return False


def _archive_row_score(row: Dict[str, object]) -> Tuple[int, int, int, int, str]:
    agent = str(row.get("analysis_agent", ""))
    return (
        3 if LLM_ANALYSIS_SCHEMA in agent else 0,
        2 if _row_has_real_formula(row) else 0,
        1 if str(row.get("analysis_version", "")) == "v2" else 0,
        len(_paper_factor_items(row)),
        str(row.get("fetched_at") or row.get("publish_time") or ""),
    )


def _archive_identity_keys(row: Dict[str, object]) -> List[str]:
    keys = [str(row.get("dedup_key", "")), _row_entry_key(row), *_row_identity_keys(row)]
    return [key for key in dict.fromkeys(keys) if key and key != _entry_key("", "", "")]


def _merge_archive_content(preferred: Dict[str, object], fallback: Dict[str, object]) -> Dict[str, object]:
    merged = dict(preferred)
    sources = []
    for item in (preferred.get("archive_sources"), fallback.get("archive_sources")):
        if isinstance(item, list):
            sources.extend(str(x) for x in item)
    for row in (preferred, fallback):
        source = row.get("archive_source") or row.get("analysis_agent") or row.get("source_id")
        if source:
            sources.append(str(source))
    if sources:
        merged["archive_sources"] = list(dict.fromkeys(sources))
    if not _row_has_real_formula(merged) and _row_has_real_formula(fallback):
        fallback_factors = fallback.get("paper_hf_factors") or fallback.get("hf_factor_points")
        if isinstance(fallback_factors, list):
            merged["paper_hf_factors"] = fallback_factors
            merged["hf_factor_points"] = fallback_factors
            merged["legacy_formula_backfill_source"] = fallback.get("archive_source") or fallback.get("analysis_agent") or "archive_fallback"
    return merged


def merge_article_rows(rows: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    merged: List[Dict[str, object]] = []
    key_to_index: Dict[str, int] = {}
    for row in rows:
        keys = _archive_identity_keys(row)
        matched = sorted({key_to_index[key] for key in keys if key in key_to_index})
        if not matched:
            key_to_index.update({key: len(merged) for key in keys})
            merged.append(dict(row))
            continue
        keep_idx = matched[0]
        for duplicate_idx in reversed(matched[1:]):
            if _archive_row_score(merged[duplicate_idx]) > _archive_row_score(merged[keep_idx]):
                keep_idx = duplicate_idx
        if _archive_row_score(row) > _archive_row_score(merged[keep_idx]):
            best = _merge_archive_content(dict(row), merged[keep_idx])
        else:
            best = _merge_archive_content(merged[keep_idx], row)
        for duplicate_idx in reversed(matched):
            if duplicate_idx == keep_idx:
                continue
            merged.pop(duplicate_idx)
            for key, index in list(key_to_index.items()):
                if index == duplicate_idx:
                    del key_to_index[key]
                elif index > duplicate_idx:
                    key_to_index[key] = index - 1
            if duplicate_idx < keep_idx:
                keep_idx -= 1
        merged[keep_idx] = best
        for key in keys:
            key_to_index[key] = keep_idx
    return sorted(merged, key=lambda x: str(x.get("publish_time", "")), reverse=True)


def collect_archive_rows(data_dir: Path, legacy_roots: Iterable[Path] = ()) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    rows.extend(read_jsonl(data_dir / "latest.jsonl"))
    for path in sorted(data_dir.glob("daily_*.jsonl")):
        rows.extend(read_jsonl(path))
    for legacy_root in legacy_roots:
        legacy_latest = legacy_root / "data" / "latest.jsonl"
        if legacy_latest.exists():
            rows.extend(read_jsonl(legacy_latest))
    return merge_article_rows(rows)


def build_analysis_archive_rows(data_dir: Path, current_rows: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    rows.extend(read_jsonl(data_dir / "analysis_archive.jsonl"))
    rows.extend(read_jsonl(data_dir / "latest.jsonl"))
    for path in sorted(data_dir.glob("daily_*.jsonl")):
        rows.extend(read_jsonl(path))
    rows.extend(current_rows)
    merged = merge_article_rows(rows)
    return [row for row in merged if _keep_for_analysis_archive(row)]


def _keep_for_analysis_archive(row: Dict[str, object]) -> bool:
    agent = str(row.get("analysis_agent") or "")
    if "schema-v6" in agent or str(row.get("analysis_version") or "") == "v2":
        return True
    if not is_display_quality_row(row):
        return False
    score = _metric_float(row.get("recommendation_score")) or 0.0
    return score >= 5.0


def render_daily_page(rows: List[Dict[str, object]], day: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = _article_cards(rows)
    html_text = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>今日 Digest {day}</title><style>{_base_style()}</style></head>
<body><div class="wrap">
    <div class="hero"><h1>今日 Digest · {day}</h1><div class="muted"><a href="{SITE_INDEX_URL}">返回首页</a></div></div>
    <div class="panel" style="margin-top:16px">{body}</div>
</div></body></html>"""
    out_path.write_text(html_text, encoding="utf-8")


def render_archive_page(rows: List[Dict[str, object]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = _article_cards(rows)
    formula_rows = sum(1 for row in rows if _row_has_real_formula(row))
    v2_rows = sum(1 for row in rows if str(row.get("analysis_version", "")) == "v2")
    v6_rows = sum(1 for row in rows if LLM_ANALYSIS_SCHEMA in str(row.get("analysis_agent", "")))
    html_text = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>All Factor Archive</title><style>{_base_style()}</style></head>
<body><div class="wrap">
    <div class="hero"><h1>All Factor Archive</h1><div class="muted">全量去重文章 {len(rows)} 篇 | v2 {v2_rows} 篇 | v6 {v6_rows} 篇 | 含真实公式 {formula_rows} 篇 | <a href="{SITE_INDEX_URL}">返回首页</a></div></div>
    <div class="panel" style="margin-top:16px" id="digest-card-list">{body}</div>
</div>{_dashboard_script()}</body></html>"""
    out_path.write_text(html_text, encoding="utf-8")


def _row_identity(row: Dict[str, object]) -> str:
    for key in ("dedup_key", "url", "title"):
        value = _normalize_text(str(row.get(key) or ""))
        if value:
            return f"{key}:{value}"
    return ""


def _home_dashboard_rows(today_rows: List[Dict[str, object]], latest_rows: List[Dict[str, object]], out_path: Path) -> List[Dict[str, object]]:
    dashboard_rows = latest_rows or today_rows
    archive_path = out_path.parent.parent / "data" / "analysis_archive.jsonl"
    if not archive_path.exists():
        return dashboard_rows
    archive_rows = read_jsonl(archive_path)
    if len(archive_rows) < len(dashboard_rows):
        return dashboard_rows

    enriched: Dict[str, Dict[str, object]] = {}
    for row in [*today_rows, *latest_rows]:
        identity = _row_identity(row)
        if identity:
            enriched[identity] = row

    merged_rows: List[Dict[str, object]] = []
    for row in archive_rows:
        identity = _row_identity(row)
        if identity and identity in enriched:
            merged = dict(row)
            merged.update(enriched[identity])
            merged_rows.append(merged)
        else:
            merged_rows.append(row)
    return merged_rows


def _recent_article_rows(rows: List[Dict[str, object]], limit: int = 10) -> List[Dict[str, object]]:
    return sorted(rows, key=lambda row: str(row.get("publish_time") or row.get("date") or ""), reverse=True)[:limit]


def render_home_page(today_rows: List[Dict[str, object]], latest_rows: List[Dict[str, object]], history: List[Dict[str, object]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    today_day = history[0]["day"] if history else datetime.now(timezone.utc).strftime("%Y%m%d")
    history_html = "".join(
        f'<li><a href="./{html.escape(str(h["html_file"]))}">{html.escape(str(h["day"]))}</a> '
        f'(<span class="muted">{int(h["count"])} 篇</span>)</li>'
        for h in history
    )
    dashboard_rows = _home_dashboard_rows(today_rows, latest_rows, out_path)
    dashboard = _dashboard_html(dashboard_rows)
    article_cards = _article_cards(dashboard_rows)
    html_text = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Paper Digest</title><style>{_base_style()}</style></head>
<body><div class="wrap">
  <div class="hero">
    <h1>Paper Digest Dashboard</h1>
                <div class="muted">今日 Digest：{today_day} | 自动抓取 + 结构化解析 + 推荐评分 · {len(dashboard_rows)} 篇可检索 | <a href="./all_factor_archive.html">全量因子归档</a> | <a href="./proxy_tier_performance.html">Proxy 分层表现</a> | <a href="http://10.9.22.11:7887/proxy_variable_audit.html" target="_blank" rel="noopener noreferrer">Proxy 人工审核台</a> | <a href="./hf_factor_faithfulness_audit.html" target="_blank" rel="noopener noreferrer">HF 忠实性审核台</a> | <a href="./reports/pipeline_health.json" target="_blank" rel="noopener noreferrer">Pipeline Health</a> | <a href="./reports/proxy_coverage_gaps.json" target="_blank" rel="noopener noreferrer">Proxy 缺口</a> | <a href="./reports/llm_pending_queue.json" target="_blank" rel="noopener noreferrer">LLM Pending</a></div>
  </div>
    {dashboard}
  <div class="grid">
        <section class="panel" id="digest-card-list">
            <h2>文章列表（默认最近 10 篇）</h2>
            {article_cards}
    </section>
    <aside class="panel">
      <h2>历史记录</h2>
      <ul>{history_html}</ul>
    </aside>
  </div>
</div>{_dashboard_script()}</body></html>"""
    out_path.write_text(html_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily paper/blog digest pipeline for factor-study.")
    parser.add_argument("--project-root", default="paper", help="Root dir for paper assets.")
    parser.add_argument("--config", default=None, help="Override config path.")
    parser.add_argument("--fetch-month", default=None, help="Fetch one arXiv submitted month, formatted as YYYYMM. Overrides PAPER_FETCH_MONTH.")
    parser.add_argument("--source-id", action="append", default=None, help="Only fetch the selected source id. Can be repeated.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse but do not write files.")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    config_path = Path(args.config).resolve() if args.config else (root / "config" / "sources.yaml")
    data_dir = root / "data"
    public_dir = root / "public"
    generated_factor_dir = data_dir / "generated_factors"
    factor_result_dir = data_dir / "factor_results"
    paper_hf_factor_dir = data_dir / "paper_hf_factor_tests_v2"
    paper_hf_result_dir = data_dir / "paper_hf_factor_results_v2"
    paper_hf_medium_result_path = data_dir / "paper_hf_factor_results_medium1" / "paper_hf_direct_proxy_tests_v2.json"
    promoted_factor_dir = data_dir / "promoted_factors"
    medium1_result_dir = data_dir / "factor_results_medium1"
    large1_result_dir = data_dir / "factor_results_large1"
    legacy_archive_root = Path(os.environ.get("PAPER_LEGACY_ARCHIVE_ROOT", str(root.parent / "my-paper-digest")))
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    defaults, sources = load_config(config_path)
    selected_source_ids = {str(source_id).strip() for source_id in (args.source_id or []) if str(source_id).strip()}
    if selected_source_ids:
        known_source_ids = {src.source_id for src in sources}
        missing_source_ids = sorted(selected_source_ids - known_source_ids)
        if missing_source_ids:
            raise ValueError("unknown --source-id: " + ", ".join(missing_source_ids))
        sources = [src for src in sources if src.source_id in selected_source_ids]
    timeout_sec = int(defaults.get("request_timeout_sec", 20))
    source_timeout_sec = int(os.environ.get("PAPER_SOURCE_TIMEOUT_SEC", str(defaults.get("source_timeout_sec", timeout_sec))))
    max_items = int(os.environ.get("PAPER_MAX_ITEMS_PER_SOURCE", str(defaults.get("max_items_per_source", 80))))
    latest_limit = int(defaults.get("latest_limit", 120))
    max_age_days = int(os.environ.get("PAPER_MAX_AGE_DAYS", str(defaults.get("max_age_days", 0))))
    user_agent = str(defaults.get("user_agent", "factor-study-paper-bot/1.0"))
    keywords = [str(k) for k in defaults.get("keywords", [])]
    fetch_month = str(args.fetch_month if args.fetch_month is not None else os.environ.get("PAPER_FETCH_MONTH", "")).strip()
    analysis_mode = str(os.environ.get("PAPER_ANALYSIS_MODE", "llm")).strip().lower()
    llm_config = {
        "model": os.environ.get("PAPER_LLM_MODEL", "gpt-4o"),
        "copilot_bin": os.environ.get("PAPER_COPILOT_BIN", "copilot"),
        "timeout_sec": int(os.environ.get("PAPER_LLM_TIMEOUT_SEC", "600")),
        "retries": int(os.environ.get("PAPER_LLM_RETRIES", "1")),
        "retry_base_sec": float(os.environ.get("PAPER_LLM_RETRY_BASE_SEC", "2")),
        "retry_max_sec": float(os.environ.get("PAPER_LLM_RETRY_MAX_SEC", "30")),
        "retry_jitter_sec": float(os.environ.get("PAPER_LLM_RETRY_JITTER_SEC", "0.5")),
        "min_interval_sec": float(os.environ.get("PAPER_LLM_MIN_INTERVAL_SEC", "3")),
        "fallback_heuristic": os.environ.get("PAPER_LLM_FALLBACK_HEURISTIC", "1") == "1",
        "refresh": os.environ.get("PAPER_LLM_REFRESH", "0") == "1",
        "max_calls_per_run": int(os.environ.get("PAPER_LLM_MAX_CALLS_PER_RUN", "10")),
        "calls_started": 0,
        "evidence_timeout_sec": ARXIV_EVIDENCE_TIMEOUT_SEC,
        "user_agent": user_agent,
    }
    if analysis_mode not in {"llm", "heuristic"}:
        raise ValueError("PAPER_ANALYSIS_MODE must be llm or heuristic")
    if analysis_mode == "llm" and not llm_config["copilot_bin"]:
        raise ValueError("PAPER_COPILOT_BIN must be set when PAPER_ANALYSIS_MODE=llm")

    now = datetime.now(timezone.utc)
    day = now.strftime("%Y%m%d")
    fetched_at = _to_utc_iso(now)

    latest_path = data_dir / "latest.jsonl"
    analysis_archive_path = data_dir / "analysis_archive.jsonl"
    daily_path = data_dir / f"daily_{day}.jsonl"

    existing = read_jsonl(latest_path)
    existing_keys = {str(r.get("dedup_key", "")) for r in existing}
    existing_keys.update(_row_entry_key(r) for r in existing)
    for r in existing:
        existing_keys.update(_row_identity_keys(r))
    daily_rows = read_jsonl(daily_path)
    for r in daily_rows:
        existing_keys.add(str(r.get("dedup_key", "")))
        existing_keys.add(_row_entry_key(r))
        existing_keys.update(_row_identity_keys(r))

    new_rows: List[Dict[str, object]] = []
    errors: List[str] = []
    for src in sources:
        if not src.enabled:
            continue
        try:
            source_max_items = src.max_items or max_items
            source_max_age_days = src.max_age_days if src.max_age_days is not None else max_age_days
            entries = fetch_entries_for_source_with_timeout(
                src,
                timeout_sec=timeout_sec,
                source_timeout_sec=source_timeout_sec,
                user_agent=user_agent,
                max_items=source_max_items,
                fetch_month=fetch_month,
                fetch_now=now,
                max_age_days=source_max_age_days,
            )
            for e in entries:
                if not _is_within_max_age(e.get("published"), now=now, max_age_days=source_max_age_days):
                    continue
                title = _normalize_text(e.get("title", ""))
                summary = _normalize_text(e.get("summary", ""))
                url = _normalize_text(e.get("url", ""))
                text = f"{title} {summary}"
                matched, tags = keyword_match(text, keywords)
                if not matched:
                    continue
                if not is_source_relevant(text, tags, src.source_type):
                    continue
                dedup_key = _entry_key(url=url, title=title, source_id=src.source_id)
                identity_keys = _entry_identity_keys(url=url, title=title)
                if dedup_key in existing_keys or any(k in existing_keys for k in identity_keys):
                    continue
                row = {
                    "publish_time": _parse_datetime(e.get("published")),
                    "source_type": src.source_type,
                    "source_name": src.source_name,
                    "source_id": src.source_id,
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "tags": tags,
                    "fetched_at": fetched_at,
                    "dedup_key": dedup_key,
                }
                new_rows.append(row)
                existing_keys.add(dedup_key)
                existing_keys.update(identity_keys)
        except Exception as exc:
            errors.append(f"{src.source_id}: {exc}")

    combined_daily = daily_rows + new_rows
    combined_latest = existing + new_rows
    combined_daily = [
        r
        for r in combined_daily
        if is_source_relevant(
            f"{_normalize_text(str(r.get('title', '')))} {_normalize_text(str(r.get('summary', '')))}",
            [str(x) for x in r.get("tags", [])],
            str(r.get("source_type", "paper")),
        )
    ]
    combined_latest = [
        r
        for r in combined_latest
        if is_source_relevant(
            f"{_normalize_text(str(r.get('title', '')))} {_normalize_text(str(r.get('summary', '')))}",
            [str(x) for x in r.get("tags", [])],
            str(r.get("source_type", "paper")),
        )
    ]
    analysis_cache: Dict[str, Dict[str, object]] = {}
    try:
        combined_daily = analyze_rows_with_cache(
            combined_daily,
            analysis_mode=analysis_mode,
            llm_config=llm_config,
            errors=errors,
            cache=analysis_cache,
        )
    except LLMRateLimitReached as exc:
        print(f"FATAL: LLM rate limit reached: {exc}", file=sys.stderr)
        sys.exit(75)

    try:
        combined_latest = analyze_rows_with_cache(
            combined_latest,
            analysis_mode=analysis_mode,
            llm_config=llm_config,
            errors=errors,
            cache=analysis_cache,
        )
    except LLMRateLimitReached as exc:
        print(f"FATAL: LLM rate limit reached: {exc}", file=sys.stderr)
        sys.exit(75)

    combined_daily = [r for r in combined_daily if is_display_quality_row(r)]
    combined_latest = [r for r in combined_latest if is_display_quality_row(r)]
    combined_latest.sort(key=lambda x: str(x.get("publish_time", "")), reverse=True)
    if latest_limit > 0:
        combined_latest = combined_latest[:latest_limit]
    combined_daily.sort(key=lambda x: str(x.get("publish_time", "")), reverse=True)

    # Optional backfill pass: re-try a limited number of fallback rows each run.
    llm_backfill_limit = int(os.environ.get("PAPER_LLM_BACKFILL_LIMIT", "2"))
    if analysis_mode == "llm" and llm_backfill_limit > 0:
        backfill_cfg = dict(llm_config)
        backfill_cfg["fallback_heuristic"] = False
        backfill_cfg["max_calls_per_run"] = max(
            0,
            int(llm_config.get("max_calls_per_run") or 0) - int(llm_config.get("calls_started") or 0),
        )
        backfill_cfg["calls_started"] = 0
        upgraded = 0
        for row in combined_daily:
            if upgraded >= llm_backfill_limit:
                break
            if str(row.get("analysis_agent", "")).startswith("paper-heuristic"):
                try:
                    ensure_analysis_fields(
                        row,
                        analysis_mode="llm",
                        llm_config=backfill_cfg,
                        errors=errors,
                    )
                    upgraded += 1
                
                
                
                except LLMCallLimitReached:
                    break
                except LLMRateLimitReached as exc:
                    print(f"FATAL: LLM rate limit reached in backfill: {exc}", file=sys.stderr)
                    sys.exit(75)
                except Exception as exc:
                    row["analysis_pending_llm"] = True
                    row["analysis_error"] = _summarize_llm_error(exc)
                    errors.append(f"analysis-backfill:{str(row.get('title', ''))[:50]}: {_summarize_llm_error(exc)}")
        if upgraded:
            by_key = {
                str(r.get("dedup_key", "")): r for r in combined_latest if str(r.get("dedup_key", ""))
            }
            for r in combined_daily:
                k = str(r.get("dedup_key", ""))
                if k:
                    by_key[k] = r
            combined_latest = sorted(
                by_key.values(),
                key=lambda x: str(x.get("publish_time", "")),
                reverse=True,
            )
            if latest_limit > 0:
                combined_latest = combined_latest[:latest_limit]

    history = build_history(data_dir)
    if not any(str(h["day"]) == day for h in history):
        history.insert(0, {"day": day, "count": len(combined_daily), "html_file": f"daily_{day}.html"})
    else:
        for h in history:
            if str(h["day"]) == day:
                h["count"] = len(combined_daily)

    if not args.dry_run:
        analysis_archive_rows = build_analysis_archive_rows(data_dir, [*combined_latest, *combined_daily])
        write_jsonl(daily_path, combined_daily)
        write_jsonl(analysis_archive_path, analysis_archive_rows)
        combined_latest = analysis_archive_rows[:latest_limit] if latest_limit > 0 else analysis_archive_rows
        write_jsonl(latest_path, combined_latest)
        generated_factor_files = write_generated_factor_files(combined_daily, generated_factor_dir)
        factor_results = load_factor_results(factor_result_dir)
        paper_hf_proxy_results = load_paper_hf_proxy_results(paper_hf_factor_dir, paper_hf_result_dir)
        paper_hf_medium_results = load_paper_hf_medium_results(promoted_factor_dir, medium1_result_dir, paper_hf_medium_result_path)
        paper_hf_large_results = load_paper_hf_large_results(promoted_factor_dir, large1_result_dir)
        medium1_results = load_promoted_factor_results(promoted_factor_dir, medium1_result_dir)
        factor_quality_results = load_factor_quality_results(data_dir / "factor_direction_report.json")
        attach_factor_results(combined_daily, factor_results)
        attach_factor_results(combined_latest, factor_results)
        attach_paper_hf_proxy_results(combined_daily, paper_hf_proxy_results)
        attach_paper_hf_proxy_results(combined_latest, paper_hf_proxy_results)
        attach_paper_hf_proxy_results(analysis_archive_rows, paper_hf_proxy_results)
        attach_paper_hf_medium_results(combined_daily, paper_hf_medium_results)
        attach_paper_hf_medium_results(combined_latest, paper_hf_medium_results)
        attach_paper_hf_medium_results(analysis_archive_rows, paper_hf_medium_results)
        attach_paper_hf_large_results(combined_daily, paper_hf_large_results)
        attach_paper_hf_large_results(combined_latest, paper_hf_large_results)
        attach_paper_hf_large_results(analysis_archive_rows, paper_hf_large_results)
        attach_promoted_factor_results(combined_daily, "factor_eval_medium1", medium1_results)
        attach_promoted_factor_results(combined_latest, "factor_eval_medium1", medium1_results)
        attach_promoted_factor_results(analysis_archive_rows, "factor_eval_medium1", medium1_results)
        attach_factor_quality_results(combined_daily, factor_quality_results)
        attach_factor_quality_results(combined_latest, factor_quality_results)
        attach_factor_quality_results(analysis_archive_rows, factor_quality_results)
        archive_rows = collect_archive_rows(data_dir, [legacy_archive_root])
        attach_factor_results(archive_rows, factor_results)
        attach_paper_hf_proxy_results(archive_rows, paper_hf_proxy_results)
        attach_paper_hf_medium_results(archive_rows, paper_hf_medium_results)
        attach_paper_hf_large_results(archive_rows, paper_hf_large_results)
        attach_promoted_factor_results(archive_rows, "factor_eval_medium1", medium1_results)
        attach_factor_quality_results(archive_rows, factor_quality_results)

        render_pages = os.environ.get("PAPER_RENDER_PAGES", "0") == "1"
        if render_pages:
            render_daily_page(combined_daily, day, public_dir / f"daily_{day}.html")
            render_home_page(combined_daily, analysis_archive_rows, history, public_dir / "index.html")
            render_archive_page(archive_rows, public_dir / "all_factor_archive.html")

        summary = {
            "run_day": day,
            "fetched_at": fetched_at,
            "fetch_month": fetch_month or None,
            "source_ids": sorted(selected_source_ids) or None,
            "analysis_mode": analysis_mode,
            "analysis_model": llm_config["model"] if analysis_mode == "llm" else "heuristic",
            "new_records": len(new_rows),
            "daily_records": len(combined_daily),
            "latest_records": len(combined_latest),
            "analysis_archive_records": len(analysis_archive_rows),
            "archive_records": len(archive_rows),
            "history_days": len(history),
            "render_pages": render_pages,
            "generated_factor_files": generated_factor_files,
            "errors": errors,
        }
        (data_dir / f"run_summary_{day}.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(
        json.dumps(
            {
                "status": "ok",
                "new_records": len(new_rows),
                "daily_total": len(combined_daily),
                "latest_total": len(combined_latest),
                "analysis_archive_total": len(analysis_archive_rows) if not args.dry_run else None,
                "generated_factor_files": generated_factor_files if not args.dry_run else 0,
                "errors": errors,
                "source_ids": sorted(selected_source_ids) or None,
                "dry_run": args.dry_run,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
