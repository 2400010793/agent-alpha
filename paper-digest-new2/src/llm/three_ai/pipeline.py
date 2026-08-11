#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.arxiv.evidence_v2 import build_evidence_pack_v2  # noqa: E402
from src.llm.common.json_utils import balance_json_closers, extract_json_block  # noqa: E402
from src.llm.common.scoring import (  # noqa: E402
    mean_recommendation_score,
    normalize_dimension_scores,
    normalize_structured_summary,
)
from src.llm.three_ai.opinion_analysis import (  # noqa: E402
    OPINION_ANALYSIS_SCHEMA,
    generate_article_opinions,
)

LLM_ANALYSIS_SCHEMA = "schema-v6"  # retained only for the legacy factor functions below
def _extract_json_block(text: str) -> Dict[str, object]:
    """Parse the first complete JSON object from occasionally noisy CLI output."""
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```[a-zA-Z]*\n?", "", value)
    line_starts = [match.start() for match in re.finditer(r"(?m)^\{", value)]
    starts = line_starts or [match.start() for match in re.finditer(r"\{", value)]
    if not starts:
        return extract_json_block(value)
    last_error: Optional[json.JSONDecodeError] = None
    for start in starts:
        depth = 0
        in_string = False
        escaped = False
        end = -1
        for index in range(start, len(value)):
            char = value[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end <= start:
            continue
        try:
            parsed = json.loads(value[start:end])
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(parsed, dict):
            return parsed
    if last_error is not None:
        raise last_error
    return extract_json_block(value)
_balance_json_closers = balance_json_closers
_mean_recommendation_score = mean_recommendation_score
_normalize_dimension_scores = normalize_dimension_scores
_normalize_structured_summary = normalize_structured_summary

# These names remain only so importing historical factor helpers fails with a
# clear message instead of accidentally reviving the old HF path.
ALLOWED_FACTOR_FIELDS: set[str] = set()
ALLOWED_HORIZONS: set[str] = set()


def _mechanism_taxonomy_context(**_kwargs: object) -> List[Dict[str, str]]:
    raise RuntimeError("HF factor generation is retired; use article_opinions")


def normalize_paper_hf_factors(_raw_factors: object) -> List[Dict[str, object]]:
    raise RuntimeError("paper_hf_factors is retired; use article_opinions")


def attach_paper_factor_proxy_analysis(_factors: List[Dict[str, object]]) -> List[Dict[str, object]]:
    raise RuntimeError("HF proxy analysis is retired; use article_opinions")


ROOT = PROJECT_ROOT

# Populated by the most recent direct API call. This lets smoke/cost runners
# record upstream usage without changing the public stage helper return values.
LAST_LLM_USAGE: Optional[Dict[str, object]] = None


def read_jsonl_valid(path: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    if not path.exists():
        return rows
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            print(json.dumps({"warning": "skip_bad_jsonl", "path": str(path), "line": line_no}, ensure_ascii=False))
    return rows


def write_jsonl(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def latest_trusted_evidence(rows: List[Dict[str, object]]) -> Tuple[Dict[str, object], Dict[str, object]]:
    for row in reversed(rows):
        pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
        quality = pack.get("quality_checks") if isinstance(pack.get("quality_checks"), dict) else {}
        if pack.get("status") == "ok" and quality.get("is_trusted"):
            return row, pack
    raise RuntimeError("no trusted ok evidence rows found")


def select_trusted_evidence(rows: List[Dict[str, object]], *, arxiv_id: str = "", title_contains: str = "") -> Tuple[Dict[str, object], Dict[str, object]]:
    arxiv_id = arxiv_id.strip().lower()
    title_contains = title_contains.strip().lower()
    if not arxiv_id and not title_contains:
        return latest_trusted_evidence(rows)
    for row in rows:
        pack = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
        quality = pack.get("quality_checks") if isinstance(pack.get("quality_checks"), dict) else {}
        if pack.get("status") != "ok" or not quality.get("is_trusted"):
            continue
        row_arxiv_id = str(row.get("arxiv_id") or pack.get("arxiv_id") or "").lower()
        row_title = str(row.get("title") or "").lower()
        if arxiv_id and row_arxiv_id != arxiv_id:
            continue
        if title_contains and title_contains not in row_title:
            continue
        return row, pack
    raise RuntimeError(f"no trusted ok evidence row matched arxiv_id={arxiv_id!r} title_contains={title_contains!r}")


def _direct_api_json(*, full_prompt: str, model: str, timeout_sec: int, api_key_env: str) -> Dict[str, object]:
    global LAST_LLM_USAGE
    env = os.environ.copy()
    api_key = env.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"missing API key environment variable: {api_key_env}")
    base_url = env.get("PAPER_LLM_BASE_URL", "https://models.github.ai/inference").rstrip("/")
    api_url = base_url + "/chat/completions"
    query = "?api-version=2024-12-01-preview"
    api_model = model if "/" in model else f"openai/{model}"
    request_body = {
        "model": api_model,
        "messages": [{"role": "user", "content": full_prompt}],
    }
    # GPT-5 models on this endpoint only accept their default temperature.
    # Older models can still use deterministic temperature=0.
    if not model.lower().startswith("gpt-5"):
        request_body["temperature"] = 0
    request = urllib.request.Request(
        api_url + query,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-Paper-Stage": os.environ.get("PAPER_LLM_STAGE", "unknown"),
            "X-Paper-Key-Alias": os.environ.get("PAPER_LLM_KEY_ALIAS", "unknown"),
            "X-Paper-Article-Id": os.environ.get("PAPER_LLM_ARTICLE_ID", "unknown"),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, timeout_sec)) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"direct API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"direct API connection failed: {exc.reason}") from exc
    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices or not isinstance(choices[0], dict):
        raise RuntimeError("direct API returned no choices")
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("direct API returned empty message content")
    LAST_LLM_USAGE = data.get("usage") if isinstance(data.get("usage"), dict) else None
    return _extract_json_block(content.strip())


def copilot_json(*, prompt: str, payload: Dict[str, object], model: str, copilot_bin: str, timeout_sec: int, api_key_env: str = "") -> Dict[str, object]:
    full_prompt = (
        f"{prompt}\n"
        "输入如下 JSON：\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n"
        "只输出一个严格合法 JSON 对象，不要 Markdown。所有 key 必须使用双引号；不要注释；不要尾逗号；不要省略号；字符串内换行必须转义。"
    )
    if os.environ.get("PAPER_LLM_DIRECT_API", "0") == "1":
        return _direct_api_json(full_prompt=full_prompt, model=model, timeout_sec=timeout_sec, api_key_env=api_key_env)
    if os.environ.get("PAPER_AIC_ONLY", "0") == "1":
        stage = os.environ.get("PAPER_LLM_STAGE", "unknown")
        article_id = os.environ.get("PAPER_LLM_ARTICLE_ID", "unknown")
        prompt_dir = os.environ.get("PAPER_AIC_PROMPT_DIR", "")
        if prompt_dir:
            prompt_path = Path(prompt_dir) / f"{stage}.prompt.txt"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(full_prompt, encoding="utf-8")
            print(f"AIC prompt saved: {prompt_path}", flush=True)
        print(f"\n===== AIC ONLY: stage={stage} article_id={article_id} model={model} =====", flush=True)
        env = os.environ.copy()
        if api_key_env:
            api_key = env.get(api_key_env)
            if api_key:
                env["PAPER_LLM_API_KEY"] = api_key
        proc = subprocess.run(
            [copilot_bin, "--model", model, "-p", full_prompt],
            timeout=max(1, timeout_sec),
            check=False,
            env=env,
        )
        print(f"===== AIC ONLY END: stage={stage} exit_code={proc.returncode} =====\n", flush=True)
        # The AIC-only mode deliberately ignores model JSON and continues to
        # the next stage. No prompt/response is written by this path.
        return {}
    env = os.environ.copy()
    if api_key_env:
        api_key = env.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"missing API key environment variable: {api_key_env}")
        env["PAPER_LLM_API_KEY"] = api_key
    proc = subprocess.run(
        [copilot_bin, "--model", model, "-p", full_prompt],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(1, timeout_sec),
        check=False,
        env=env,
    )
    # Preserve the CLI accounting footer while keeping model output private
    # for JSON parsing. This makes AIC visible and auditable in batch runs.
    aic_lines = []
    for stream_name, stream in (("stdout", proc.stdout or ""), ("stderr", proc.stderr or "")):
        for line in stream.splitlines():
            lowered = line.lower()
            is_footer = stream_name == "stderr" and any(term in lowered for term in ("aic", "credit", "token", "usage", "cost"))
            if is_footer:
                aic_lines.append({"stream": stream_name, "text": line.strip()})
    if aic_lines:
        event = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stage": os.environ.get("PAPER_LLM_STAGE", "unknown"),
            "article_id": os.environ.get("PAPER_LLM_ARTICLE_ID", "unknown"),
            "model": model,
            "aic": aic_lines,
        }
        aic_log = ROOT / "logs" / "copilot_aic_20260724.jsonl"
        aic_log.parent.mkdir(parents=True, exist_ok=True)
        with aic_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        print(json.dumps({"status": "copilot_aic", **event}, ensure_ascii=False), flush=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()[:800]
        raise RuntimeError(f"copilot {model} exit code {proc.returncode}: {stderr}")
    content = (proc.stdout or "").strip()
    if not content:
        raise RuntimeError(f"copilot {model} returned empty output")
    try:
        return _extract_json_block(content)
    except json.JSONDecodeError as exc:
        logs_dir = ROOT / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        raw_path = logs_dir / f"llm_json_parse_error_{int(time.time())}.txt"
        raw_path.write_text(content, encoding="utf-8")
        # Copilot occasionally emits literal tabs/newlines inside JSON strings.
        # Escape those controls before applying the existing lightweight repairs.
        repaired_chars: List[str] = []
        in_string = False
        escaped = False
        for char in content:
            if char == '"' and not escaped:
                in_string = not in_string
            if in_string and ord(char) < 32:
                repaired_chars.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(char, f"\\u{ord(char):04x}"))
            else:
                repaired_chars.append(char)
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
        repaired = "".join(repaired_chars)
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
        repaired = re.sub(r"(?<!\\)\\(?![\"\\/bfnrtu])", r"\\\\", repaired)
        try:
            return _extract_json_block(repaired)
        except json.JSONDecodeError:
            balanced = _balance_json_closers(repaired)
            try:
                return _extract_json_block(balanced)
            except json.JSONDecodeError:
                raise RuntimeError(f"copilot {model} returned invalid JSON: {exc}; raw saved to {raw_path}") from exc


def _balance_json_closers(text: str) -> str:
    stack: List[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in "}]" and stack and stack[-1] == char:
            stack.pop()
    return text + "".join(reversed(stack))


def _reading_note_schema() -> Dict[str, object]:
    return {
        "schema_version": "reading_note_v1",
        "central_claim": "string",
        "problem": "string",
        "method_logic": "string",
        "core_formulas": [],
        "mechanism_chain": [],
        "data_and_empirical_setup": {},
        "datasets_and_sample_split": [],
        "experimental_setup": [],
        "baselines": [],
        "metrics": [],
        "empirical_results": [],
        "experimental_formulas": [],
        "code_or_algorithm_logic": [],
        "conclusion_claims": [],
        "key_results": [],
        "limitations": [],
        "not_disclosed": [],
        "faithfulness_constraints_for_next_llm": [],
        "score_dimensions": {
            "relevance": {"score": "integer 1-10", "comment": "string", "evidence": "string", "critique": "string"},
            "mechanism": {"score": "integer 1-10", "comment": "string", "evidence": "string", "critique": "string"},
            "statistical": {"score": "integer 1-10", "comment": "string", "evidence": "string", "critique": "string"},
            "implementation": {"score": "integer 1-10", "comment": "string", "evidence": "string", "critique": "string"},
            "cost_sensitivity": {"score": "integer 1-10", "comment": "string", "evidence": "string", "critique": "string"},
            "generality": {"score": "integer 1-10", "comment": "string", "evidence": "string", "critique": "string"},
        },
        "recommendation_score": "average score as number",
        "hf_mechanism_category": "exactly one category id or none",
        "hf_mechanism_selection_evidence": [],
        "opinion_category": "exactly one category id or none",
        "opinion_selection_evidence": [],
        "research_topic_category": "one broad research topic category id",
        "research_topic_selection_basis": "string",
    }


def reading_note_score(reading_note: Dict[str, object]) -> float:
    dimensions = reading_note.get("score_dimensions") if isinstance(reading_note.get("score_dimensions"), dict) else {}
    scores: List[float] = []
    for value in dimensions.values():
        if not isinstance(value, dict):
            continue
        try:
            score = float(value.get("score") or 0)
        except (TypeError, ValueError):
            continue
        if score > 0:
            scores.append(score)
    if scores:
        return round(sum(scores) / len(scores), 1)
    try:
        return round(float(reading_note.get("recommendation_score") or 0), 1)
    except (TypeError, ValueError):
        return 0.0


OPINION_CATEGORY_IDS = (
    "order_book_pressure", "depute_imbalance", "trade_impact",
    "price_volume_divergence", "spread_liquidity", "short_reversal",
    "short_momentum", "volatility_burst", "book_shape", "trading_rhythm",
)

RESEARCH_TOPIC_CATEGORY_IDS = (
    "asset_pricing_factor", "portfolio_optimization", "market_microstructure",
    "order_flow", "volatility", "transaction_cost", "return_prediction",
    "risk_management", "derivatives", "financial_ml", "other",
)

RESEARCH_TOPIC_LABELS = {
    "asset_pricing_factor": "资产定价与因子",
    "portfolio_optimization": "组合优化",
    "market_microstructure": "市场微观结构",
    "order_flow": "订单流",
    "volatility": "波动率",
    "transaction_cost": "交易成本",
    "return_prediction": "收益预测",
    "risk_management": "风险管理",
    "derivatives": "衍生品",
    "financial_ml": "金融机器学习",
    "other": "其他",
}


def infer_research_topic_category(row: Dict[str, object], note: Dict[str, object]) -> str:
    """Assign a broad research topic without changing the HF mechanism class.

    This is deliberately deterministic and metadata/evidence based. It is a
    display topic, not a claim that the paper contains a tradable factor.
    """
    existing = str(note.get("research_topic_category") or row.get("research_topic_category") or "").strip()
    if existing in RESEARCH_TOPIC_CATEGORY_IDS:
        return existing
    text = " ".join(str(note.get(key) or "") for key in (
        "central_claim", "problem", "method_logic", "data_and_empirical_setup",
        "datasets_and_sample_split", "experimental_setup", "key_results",
        "conclusion_claims", "limitations",
    ))
    text = (str(row.get("title") or "") + " " + str(row.get("summary") or "") + " " + text).lower()
    rules = (
        ("derivatives", ("option", "implied volatility", "svi", "期权", "衍生品")),
        ("transaction_cost", ("transaction cost", "trading cost", "turnover cost", "交易成本", "滑点")),
        ("order_flow", ("order flow", "hawkes", "订单流", "event arrival", "事件到达")),
        ("market_microstructure", ("limit order book", "order book", "lob", "microstructure", "限价订单簿", "微观结构")),
        ("volatility", ("volatility", "rough volatility", "波动率", "波动")),
        ("asset_pricing_factor", ("factor", "factors", "asset pricing", "risk premia", "anomaly", "因子", "资产定价")),
        ("portfolio_optimization", ("portfolio optimization", "mean-variance", "black-litterman", "组合优化", "资产配置")),
        ("return_prediction", ("return prediction", "stock return", "收益预测", "股票收益")),
        ("risk_management", ("risk management", "stress test", "bank run", "风险管理", "压力测试")),
        ("financial_ml", ("machine learning", "deep learning", "neural network", "机器学习", "深度学习")),
    )
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return category
    return "other"


def normalize_shared_category(note: Dict[str, object]) -> Dict[str, object]:
    """Use one first-stage category for both downstream analysis lines.

    ``none`` is valid when the paper lacks sufficient evidence for any
    mechanism category.
    """
    category = str(note.get("hf_mechanism_category") or "")
    if category not in OPINION_CATEGORY_IDS and category != "none":
        category = str(note.get("opinion_category") or "")
    if category not in OPINION_CATEGORY_IDS and category != "none":
        category = "none"
    note["hf_mechanism_category"] = category
    note["opinion_category"] = category
    return note


def _compact_text(value: object, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _compact_items(value: object, *, item_limit: int = 8, text_limit: int = 420) -> List[object]:
    items = value if isinstance(value, list) else [value] if value else []
    compacted: List[object] = []
    for item in items[:item_limit]:
        if isinstance(item, dict):
            compacted.append({str(k): _compact_text(v, text_limit) if not isinstance(v, (list, dict)) else v for k, v in list(item.items())[:10]})
        else:
            compacted.append(_compact_text(item, text_limit))
    return compacted


def _compact_value_for_merge(value: object, *, depth: int = 0) -> object:
    """Bound chunk-note size before sending it to the merge call."""
    if isinstance(value, str):
        return _compact_text(value, 600)
    if isinstance(value, list):
        return [_compact_value_for_merge(item, depth=depth + 1) for item in value[:8]]
    if isinstance(value, dict):
        if depth >= 2:
            return _compact_text(json.dumps(value, ensure_ascii=False), 600)
        return {
            str(key): _compact_value_for_merge(item, depth=depth + 1)
            for key, item in list(value.items())[:12]
        }
    return value


def compact_chunk_note_for_merge(note: Dict[str, object]) -> Dict[str, object]:
    """Keep merge evidence and anchors while avoiding a second full-size payload."""
    return {
        str(key): _compact_value_for_merge(value)
        for key, value in note.items()
    }


def compact_reading_note_for_factor_stage(reading_note: Dict[str, object]) -> Dict[str, object]:
    return {
        "schema_version": reading_note.get("schema_version"),
        "central_claim": _compact_text(reading_note.get("central_claim"), 700),
        "problem": _compact_text(reading_note.get("problem"), 700),
        "method_logic": _compact_text(reading_note.get("method_logic"), 900),
        "core_formulas": _compact_items(reading_note.get("core_formulas"), item_limit=8, text_limit=600),
        "mechanism_chain": _compact_items(reading_note.get("mechanism_chain"), item_limit=8, text_limit=500),
        "data_and_empirical_setup": reading_note.get("data_and_empirical_setup") if isinstance(reading_note.get("data_and_empirical_setup"), dict) else _compact_text(reading_note.get("data_and_empirical_setup"), 700),
        "experimental_formulas": _compact_items(reading_note.get("experimental_formulas"), item_limit=6, text_limit=550),
        "code_or_algorithm_logic": _compact_items(reading_note.get("code_or_algorithm_logic"), item_limit=6, text_limit=550),
        "conclusion_claims": _compact_items(reading_note.get("conclusion_claims"), item_limit=6, text_limit=420),
        "key_results": _compact_items(reading_note.get("key_results"), item_limit=8, text_limit=420),
        "limitations": _compact_items(reading_note.get("limitations"), item_limit=8, text_limit=420),
        "not_disclosed": _compact_items(reading_note.get("not_disclosed"), item_limit=10, text_limit=260),
        "faithfulness_constraints_for_next_llm": _compact_items(reading_note.get("faithfulness_constraints_for_next_llm"), item_limit=10, text_limit=360),
        "score_dimensions": reading_note.get("score_dimensions") if isinstance(reading_note.get("score_dimensions"), dict) else {},
        "recommendation_score": reading_note.get("recommendation_score"),
        "source_chunk_count": reading_note.get("source_chunk_count"),
    }


NON_ACTIONABLE_FORMULA_ROLES = {"setup_definition", "calibration_step", "robustness_result"}
NON_ACTIONABLE_FORMULA_TYPES = {"intermediate_definition", "estimation_procedure"}


def _factor_actionability_issue(factor: Dict[str, object]) -> str:
    source_type = str(factor.get("formula_source_type") or "unknown")
    role = str(factor.get("formula_role_in_paper") or "unknown")
    rationale = str(factor.get("why_this_formula_is_actionable") or "")
    mechanism_formula = str(factor.get("mechanism_formula") or "").strip()
    if not mechanism_formula:
        return "missing mechanism_formula"
    whole_paper_formula = str(factor.get("whole_paper_formula") or "").strip()
    if not whole_paper_formula:
        return "missing whole_paper_formula"
    whole_paper_basis = factor.get("whole_paper_basis")
    if not isinstance(whole_paper_basis, dict):
        return "missing whole_paper_basis"
    for key in ("problem", "method", "final_result_or_formula", "limitations_or_data"):
        if not str(whole_paper_basis.get(key) or "").strip():
            return f"whole_paper_basis.{key} is empty"
    if source_type in NON_ACTIONABLE_FORMULA_TYPES:
        return f"formula_source_type={source_type} is not directly actionable"
    if role in NON_ACTIONABLE_FORMULA_ROLES:
        return f"formula_role_in_paper={role} is not a final mechanism"
    if source_type == "result_statement" and role != "empirical_decomposition":
        return "result_statement is not tied to an empirical decomposition"
    if source_type == "llm_proxy_mapping":
        return "llm_proxy_mapping cannot be emitted as a paper factor"
    if source_type == "mechanism_derived" and (not rationale or "whole_paper" not in rationale and "全文" not in rationale and "机制" not in rationale):
        return "mechanism_derived lacks whole-paper derivation rationale"
    return ""


def filter_actionable_paper_hf_factors(factors: List[Dict[str, object]]) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    kept: List[Dict[str, object]] = []
    dropped: List[Dict[str, object]] = []
    for factor in factors:
        issue = _factor_actionability_issue(factor)
        if issue:
            dropped.append({"name": factor.get("name"), "reason": issue, "formula_source_type": factor.get("formula_source_type"), "formula_role_in_paper": factor.get("formula_role_in_paper")})
            continue
        kept.append(factor)
    return kept, dropped


def build_reading_chunks(row: Dict[str, object], evidence_pack: Dict[str, object]) -> List[Dict[str, object]]:
    evidence_pack_v2 = build_evidence_pack_v2(evidence_pack)
    article_meta = {
        "title": row.get("title"),
        "url": row.get("url"),
        "source_id": row.get("source_id"),
        "source_name": row.get("source_name"),
        "tags": row.get("tags", []),
    }
    abstract = str(row.get("summary") or "")[:3000]
    source_anchor = {
        "source_kind": evidence_pack.get("source_kind"),
        "main_source_file": evidence_pack.get("main_source_file"),
        "source_files": evidence_pack.get("source_files"),
    }
    return [
        {
            "chunk_id": "overview_claims",
            "task": "Read the paper frame: problem, central claim, contribution, mechanism outline, section map, and intro claims.",
            "article_meta": article_meta,
            "abstract": abstract,
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
            "article_meta": article_meta,
            "evidence": {
                "formula_evidence": evidence_pack_v2.get("formula_evidence"),
                "variable_definitions": evidence_pack_v2.get("variable_definitions"),
                "source_anchor": source_anchor,
            },
        },
        {
            "chunk_id": "method_data_results",
            "task": "Extract method logic, data/sample setup, empirical design, and disclosed results. Mark anything not disclosed explicitly.",
            "article_meta": article_meta,
            "evidence": {
                "method_evidence": evidence_pack_v2.get("method_evidence"),
                "data_sample_evidence": evidence_pack_v2.get("data_sample_evidence"),
                "empirical_results": evidence_pack_v2.get("empirical_results"),
                "source_anchor": source_anchor,
            },
        },
        {
            "chunk_id": "experimental_code",
            "task": "Read only experimental formulas and algorithm/code snippets. Extract what the experiment/code computes, inputs/outputs, evaluation equations, and implementation constraints. Do not infer paper conclusions beyond this chunk.",
            "article_meta": article_meta,
            "evidence": {
                "experimental_formula_evidence": evidence_pack_v2.get("experimental_formula_evidence"),
                "code_evidence": evidence_pack_v2.get("code_evidence"),
                "source_anchor": source_anchor,
            },
        },
        {
            "chunk_id": "conclusion_limits",
            "task": "Read only conclusion/discussion/limitations evidence. Extract final author claims, caveats, future-work boundaries, and constraints for downstream factor generation. Do not treat conclusion text alone as formula/statistical evidence.",
            "article_meta": article_meta,
            "evidence": {
                "conclusion_evidence": evidence_pack_v2.get("conclusion_evidence"),
                "quality": evidence_pack_v2.get("quality"),
                "missing_evidence": evidence_pack_v2.get("missing_evidence"),
                "excluded_sections": evidence_pack_v2.get("excluded_sections"),
                "source_anchor": source_anchor,
            },
        },
    ]


def build_chunk_reading_note(chunk: Dict[str, object], *, model: str, copilot_bin: str, timeout_sec: int, api_key_env: str = "") -> Dict[str, object]:
    prompt = (
        "你是第一阶段分部阅读模型，只阅读当前 chunk，不生成交易因子。"
        "必须忠实抽取当前 chunk 中披露的证据；不能使用当前 chunk 没给出的信息。"
        "如果信息未披露，明确写'输入未披露'。不得补造样本、t值、Sharpe、IC、交易成本、样本外或容量。"
        "输出 schema_version='reading_note_chunk_v1'，并保留 chunk_id。"
    )
    payload = {
        "chunk": chunk,
        "required_schema": {
            "schema_version": "reading_note_chunk_v1",
            "chunk_id": chunk.get("chunk_id"),
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
        },
    }
    note = copilot_json(prompt=prompt, payload=payload, model=model, copilot_bin=copilot_bin, timeout_sec=timeout_sec, api_key_env=api_key_env)
    note.setdefault("schema_version", "reading_note_chunk_v1")
    note.setdefault("chunk_id", chunk.get("chunk_id"))
    return note


def merge_chunk_reading_notes(row: Dict[str, object], chunk_notes: List[Dict[str, object]], *, model: str, copilot_bin: str, timeout_sec: int, api_key_env: str = "") -> Dict[str, object]:
    prompt = (
        "你是第一阶段合并阅读模型。只基于 reading_note_chunk_v1 列表合并成一份 reading_note_v1。"
        "不得引入 chunk notes 没有的证据；冲突时保留更保守说法，并写入 limitations 或 not_disclosed。"
        "核心公式、变量定义、数据设置和关键结果必须保留来源 chunk_id 或 evidence_ref。"
        "尽可能地保留数据集，实验测试内容和算法逻辑的来源证据。"
        "必须把 experimental_code chunk 的 experimental_formulas/code_or_algorithm_logic 合并到 reading_note_v1 对应字段；必须把 conclusion_limits chunk 的 conclusion_claims/limitations/faithfulness_constraints_for_next_llm 合并到对应字段。"
        "结论/Discussion/Limitations 只用于作者最终主张、边界和约束；不能把结论单独当作公式或统计证据。"
        "必须在第一阶段完成论文级维度评分 score_dimensions，包含 relevance/mechanism/statistical/implementation/cost_sensitivity/generality；每项score为1-10，并给comment/evidence/critique。"
        "recommendation_score为六个维度均值。这个评分用于决定是否启动第二阶段因子生成。"
        "同时必须在本次合并中完成高频机制分类，并且只能选择一个 hf_mechanism_category；不能返回多个类别，不能调用额外分类模型。"
        "可选类别只有：order_book_pressure、depute_imbalance、trade_impact、price_volume_divergence、spread_liquidity、short_reversal、short_momentum、volatility_burst、book_shape、trading_rhythm、none。"
        "选择标准是：优先选择全文问题、方法/机制链、最终结果和数据条件共同支持的唯一主机制，而不是根据单个关键词选择。"
        "如果论文没有明确的高频机制证据，必须选择 none。必须输出 hf_mechanism_selection_evidence，引用支持该选择的 chunk_id 或 evidence_ref；选择 none 时说明缺失证据。"
        "两条主线必须共用同一个 shared_category：opinion_category 必须与 hf_mechanism_category 完全一致；选择十个类别中的一个，或在证据不足时选择 none；不能返回多个类别。"
        "选择最能代表论文最终机制和可发展想法的唯一角度，并分别输出 hf_mechanism_selection_evidence 和 opinion_selection_evidence；不能根据关键词机械选择。证据不足时必须选择 none，并说明缺失证据。"
        "输出 schema_version='reading_note_v1'。"
    )
    payload = {
        "article_meta": {
            "title": row.get("title"),
            "url": row.get("url"),
            "source_id": row.get("source_id"),
            "source_name": row.get("source_name"),
            "tags": row.get("tags", []),
        },
        # The fifth chunk call returns notes, not the original evidence. Keep
        # those notes and their evidence anchors, but bound their size before
        # sending them again in the sixth merge call.
        "chunk_notes": [compact_chunk_note_for_merge(note) for note in chunk_notes],
        "required_schema": _reading_note_schema(),
    }
    note = copilot_json(prompt=prompt, payload=payload, model=model, copilot_bin=copilot_bin, timeout_sec=timeout_sec, api_key_env=api_key_env)
    note.setdefault("schema_version", "reading_note_v1")
    normalize_shared_category(note)
    note["source_chunk_count"] = len(chunk_notes)
    note["research_topic_category"] = infer_research_topic_category(row, note)
    note.setdefault("research_topic_selection_basis", "基于文章标题、摘要和 reading_note 字段的确定性关键词映射；不代表存在可交易因子。")
    note["recommendation_score"] = reading_note_score(note)
    if not note.get("mechanism_chain"):
        chain: List[str] = []
        for chunk in chunk_notes:
            if not isinstance(chunk, dict):
                continue
            chunk_id = str(chunk.get("chunk_id") or "chunk")
            for key in ("central_claims", "method_logic", "core_formulas", "key_results"):
                value = chunk.get(key)
                items = value if isinstance(value, list) else [value] if value else []
                for item in items:
                    text = json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item or "")
                    text = " ".join(text.split())
                    if text:
                        chain.append(f"{chunk_id}: {text[:280]}")
                    if len(chain) >= 8:
                        break
                if len(chain) >= 8:
                    break
            if len(chain) >= 8:
                break
        note["mechanism_chain"] = chain
    return note


def build_reading_note(row: Dict[str, object], evidence_pack: Dict[str, object], *, model: str, copilot_bin: str, timeout_sec: int, api_key_env: str = "") -> Dict[str, object]:
    evidence_pack_v2 = build_evidence_pack_v2(evidence_pack)
    prompt = (
        "你是第一阶段论文阅读模型，只负责把论文证据压缩成忠实的结构化阅读笔记，不生成交易因子。"
        "必须优先使用 evidence_pack_v2；旧 evidence_pack 只用于补充核对。"
        "保留中心含义、核心公式、变量定义、文章逻辑、样本/实证设置、关键结果、局限和未披露证据。"
        "实验信息必须单独、具体抽取到 datasets_and_sample_split、experimental_setup、baselines、metrics、empirical_results；每项尽量列出论文中的数据集名称、样本划分、实验设置、基准模型全名、指标定义和实际结果数值，并为每条记录保留 source_anchor 或 evidence_ref。找不到时写入 not_disclosed，不要用概括性结论替代具体证据。"
        "不得使用结论/Discussion/未来工作作为核心证据；不得补造样本、t值、Sharpe、IC、交易成本、样本外或容量。"
        "每条关键主张、公式和变量定义都要尽量给 source_anchor 或 evidence_ref。"
        "必须给score_dimensions和recommendation_score；评分会决定是否启动第二阶段因子生成。"
            "必须从十个类别中选择一个，或在证据不足时选择 none；并将 hf_mechanism_category 和 opinion_category 都设置为同一个 shared_category；禁止返回多个类别。"
        "另外必须输出一个宽泛的 research_topic_category，用于论文主题展示，不受高频机制类别限制；可选：asset_pricing_factor、portfolio_optimization、market_microstructure、order_flow、volatility、transaction_cost、return_prediction、risk_management、derivatives、financial_ml、other。"
        "输出 schema_version='reading_note_v1'。"
    )
    payload = {
        "article_meta": {
            "title": row.get("title"),
            "url": row.get("url"),
            "source_id": row.get("source_id"),
            "source_name": row.get("source_name"),
            "tags": row.get("tags", []),
        },
        "abstract": str(row.get("summary") or "")[:3000],
        "evidence_pack_v2": evidence_pack_v2,
        "evidence_pack": evidence_pack,
        "required_schema": _reading_note_schema(),
    }
    note = copilot_json(prompt=prompt, payload=payload, model=model, copilot_bin=copilot_bin, timeout_sec=timeout_sec, api_key_env=api_key_env)
    note.setdefault("schema_version", "reading_note_v1")
    normalize_shared_category(note)
    note["research_topic_category"] = infer_research_topic_category(row, note)
    note.setdefault("research_topic_selection_basis", "基于文章标题、摘要和 reading_note 字段的确定性关键词映射；不代表存在可交易因子。")
    note["recommendation_score"] = reading_note_score(note)
    return note


def build_reading_note_chunked(
    row: Dict[str, object],
    evidence_pack: Dict[str, object],
    *,
    model: str,
    copilot_bin: str,
    timeout_sec: int,
    api_key_env: str = "",
    chunk_cache_dir: Optional[Path] = None,
) -> Dict[str, object]:
    chunks = build_reading_chunks(row, evidence_pack)
    chunk_notes: List[Dict[str, object]] = []
    if chunk_cache_dir is not None:
        chunk_cache_dir.mkdir(parents=True, exist_ok=True)
    article_id = str(row.get("arxiv_id") or row.get("source_id") or "article").replace("/", "_")
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "chunk")
        cache_path = chunk_cache_dir / f"{article_id}.{chunk_id}.json" if chunk_cache_dir else None
        note: Optional[Dict[str, object]] = None
        if cache_path and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and cached.get("chunk_id") == chunk_id:
                    note = cached
            except (OSError, json.JSONDecodeError):
                note = None
        if note is None:
            note = build_chunk_reading_note(chunk, model=model, copilot_bin=copilot_bin, timeout_sec=timeout_sec, api_key_env=api_key_env)
            if cache_path:
                temporary = cache_path.with_suffix(cache_path.suffix + ".part")
                temporary.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(cache_path)
        chunk_notes.append(note)
    merged = merge_chunk_reading_notes(row, chunk_notes, model=model, copilot_bin=copilot_bin, timeout_sec=timeout_sec, api_key_env=api_key_env)
    merged["chunk_notes"] = chunk_notes
    return merged


def build_reading_note_single_call_chunked(row: Dict[str, object], evidence_pack: Dict[str, object], *, model: str, copilot_bin: str, timeout_sec: int, api_key_env: str = "") -> Dict[str, object]:
    chunks = build_reading_chunks(row, evidence_pack)
    prompt = (
        "你是第一阶段单次调用分块阅读模型。输入已经被本地拆成多个 evidence chunks；"
        "你必须按 chunk_id 分别阅读，再在同一次输出中合并成一份 reading_note_v1。"
        "分块是为了保留证据结构，不代表可以忽略任何 chunk；必须覆盖 overview_claims、formula_variables、method_data_results、experimental_code、conclusion_limits。"
        "必须从 method_data_results、experimental_code 和 conclusion_limits 中单独抽取 datasets_and_sample_split、experimental_setup、baselines、metrics、empirical_results；baseline 必须列出论文明确出现的模型名称，指标必须解释含义，结果必须保留实际数值或明确写输入未披露。"
        "不得生成交易因子；不得补造样本、t值、Sharpe、IC、交易成本、样本外或容量。"
        "如果信息未披露，明确写'输入未披露'。"
        "核心公式、变量定义、数据设置和关键结果必须保留来源 chunk_id 或 evidence_ref。"
        "结论/Discussion/Limitations 只用于作者最终主张、边界和约束；不能把结论单独当作公式或统计证据。"
        "必须给score_dimensions和recommendation_score；评分会决定是否启动第二阶段因子生成。"
        "必须从十个高频机制类别中选择一个，或在证据不足时选择 none；并将 hf_mechanism_category 和 opinion_category 都设置为同一个 shared_category；禁止返回多个类别。"
        "另外必须输出一个宽泛的 research_topic_category，用于论文主题展示，不受高频机制类别限制；可选：asset_pricing_factor、portfolio_optimization、market_microstructure、order_flow、volatility、transaction_cost、return_prediction、risk_management、derivatives、financial_ml、other。"
        "输出 schema_version='reading_note_v1'。"
    )
    payload = {
        "article_meta": {
            "title": row.get("title"),
            "url": row.get("url"),
            "source_id": row.get("source_id"),
            "source_name": row.get("source_name"),
            "tags": row.get("tags", []),
        },
        "reading_chunks": chunks,
        "required_schema": _reading_note_schema(),
    }
    note = copilot_json(prompt=prompt, payload=payload, model=model, copilot_bin=copilot_bin, timeout_sec=timeout_sec, api_key_env=api_key_env)
    note.setdefault("schema_version", "reading_note_v1")
    normalize_shared_category(note)
    note["source_chunk_count"] = len(chunks)
    note["reading_mode"] = "single_call_chunked"
    note["research_topic_category"] = infer_research_topic_category(row, note)
    note.setdefault("research_topic_selection_basis", "基于文章标题、摘要和 reading_note 字段的确定性关键词映射；不代表存在可交易因子。")
    note["recommendation_score"] = reading_note_score(note)
    return note


def generate_hf_factors(row: Dict[str, object], reading_note: Dict[str, object], evidence_pack: Dict[str, object], *, model: str, copilot_bin: str, timeout_sec: int, api_key_env: str = "") -> Dict[str, object]:
    tags = [str(x) for x in row.get("tags", [])]
    summary = str(row.get("summary") or "")
    compact_reading_note = compact_reading_note_for_factor_stage(reading_note)
    mechanism_taxonomy_context = _mechanism_taxonomy_context(
        title=str(row.get("title") or ""),
        summary=summary,
        tags=tags,
        evidence_pack=evidence_pack,
    )
    prompt = (
        "你是第二阶段高频因子设计模型。只能基于 reading_note_v1 和 context_providers 生成 paper_hf_factors。"
        "输出必须是紧凑、严格合法 JSON；不要 Markdown；不要解释 JSON 之外的内容。"
        "第二阶段输出必须先给 seed_factors：至少1个且最多3个；其中至少1个 seed_factors.kind 必须是 faithful_seed_factor，严格忠于原文问题、方法、变量、结果或限制，不必拘泥于公式，也不必直接可交易。"
        "faithful_seed_factor 的 purpose 是保留论文原始启发和可复核锚点：它可以是'改进波动率测量的种子因子'、'识别订单流状态的种子因子'、'描述非平稳漂移的种子因子'，但必须能被 reading_note 明确支持，不能加入文本之外的想象。"
        "除 faithful_seed_factor 外，其余 seed_factors.kind 可以是 formula_extended_seed_factor 或 mechanism_extended_seed_factor，允许基于原文公式、机制链、变量定义或关键结果做合理发挥，但必须标明从哪些原文证据扩展。"
        "paper_hf_factors 可以来自 seed_factors：至少一个 paper_hf_factor 应引用一个 faithful_seed_factor 的 seed_factor_id；若没有足够证据生成可行动因子，也必须保留 faithful_seed_factor，并允许 paper_hf_factors 为空。"
        "允许基于论文全文最终机制创造因子公式；如果论文没有直接给出可交易因子，应优先构造 mechanism_derived 因子，而不是把中间定义/校准步骤当因子。"
        "mechanism_derived 必须来自 reading_note 的最终机制链、最终模型、最终分解、关键结果或限制，不能来自孤立公式；必须明确写'由机制推导，输入未直接给出因子'。"
        "不要把自创因子伪装成论文原公式；自创公式的 formula_source_type 必须是 mechanism_derived。"
        "生成因子必须分两层：先识别 whole_paper_formula，再给出 mechanism_formula。"
        "whole_paper_formula 是全文机制公式：它必须由论文全文问题设定、核心方法/模型、最终公式或关键结果、限制/数据条件共同支撑；可以是文章原文的最终全文公式，也可以是对全文机制的综合表达。"
        "mechanism_formula 是最终因子公式：它可以直接等于文章里的 whole_paper_formula，也可以是不基于单个文章公式、而是结合全文内容创造出的 mechanism_derived 因子公式。"
        "如果 mechanism_formula 直接采用文章公式，该公式必须是 whole_paper_formula，不能是早期定义、局部估计式、校准式或单个结果陈述。"
        "如果 mechanism_formula 是自创因子公式，formula_source_type 必须是 mechanism_derived，并且必须说明它如何由 whole_paper_formula 和全文证据推导出来。"
        "生成因子前必须完成全文一致性检查：候选因子必须同时被论文问题设定、核心方法/模型、最终公式或关键结果、限制/数据条件四类内容支持；缺任一类支持时不要输出该因子。"
        "每个因子必须输出 whole_paper_formula 和 whole_paper_basis；whole_paper_basis 包含 problem/method/final_result_or_formula/limitations_or_data 四项短引用；不能只引用单个公式或单个段落。"
        "每个因子必须引用 reading_note 的公式、机制链、关键结果或限制。"
        "禁止输出'论文高频因子1'这类占位名称；name必须概括具体机制。"
        "每个因子的 mechanism_formula、meaning、paper_mechanism、source_evidence 必须非空，但要短；mechanism_formula 禁止使用省略号、...、…、etc.、等等；如果原公式太长，必须摘录完整的关键等式项并在 source_evidence 标明公式来源。"
        "必须先基于整篇文章逻辑链判断最终可用机制，不能看到一个早期/铺垫/估计公式就生成因子。"
        "必须区分公式来源：formula_source_type只能是final_model_formula/intermediate_definition/estimation_procedure/result_statement/mechanism_derived/llm_proxy_mapping之一。"
        "final_model_formula表示论文最终模型、最终分解或最终用于解释/预测/控制的机制公式；intermediate_definition表示变量/空间/算子定义；estimation_procedure表示参数估计、正则化或数值解法；result_statement表示论文已有结果、回归分解或实证陈述；mechanism_derived表示基于全文最终机制推导出的因子表达。"
        "formula_source_type为intermediate_definition或estimation_procedure时，不能直接生成可用因子；如果它启发了最终机制，应改写成 mechanism_derived 因子公式，并解释完整推导链。"
        "formula_source_quote必须给出支撑mechanism_formula的原文公式片段或reading_note引用；如果不是paper_formula，必须在paper_mechanism中说明不是作者直接给出的交易因子。"
        "每个因子还必须输出 formula_role_in_paper 和 why_this_formula_is_actionable；formula_role_in_paper只能是final_mechanism/setup_definition/calibration_step/robustness_result/empirical_decomposition/proxy_mapping。"
        "why_this_formula_is_actionable必须说明该公式如何连接到文章最终逻辑、最终结果或可交易/风险控制机制；对于 mechanism_derived，必须写出从论文机制到因子公式的推导链。"
        "source_evidence引用 reading_note 的 chunk_id、core_formulas、mechanism_chain、key_results 或 limitations。"
        "paper_hf_formula_plan 只能使用已声明模板/算子族；不得输出任意 Python 表达式作为正式模板。"
        "score_dimensions只能放在顶层，绝不能放进paper_hf_factors的单个因子内部。"
        "score_dimensions必须包含 relevance/mechanism/statistical/implementation/cost_sensitivity/generality；每项含score,comment,evidence,critique，score为1-10。"
        f"输出 schema_version='{LLM_ANALYSIS_SCHEMA}'；seed_factors给1到3个且至少1个faithful_seed_factor；paper_hf_factors 给0到2个；宁可少给，也绝不能为凑数输出中间定义、校准步骤、估计过程、数值解法或弱连接公式。"
    )
    payload = {
        "article_meta": {
            "title": row.get("title"),
            "url": row.get("url"),
            "tags": tags,
        },
        "reading_note": compact_reading_note,
        "context_providers": {
            "mechanism_taxonomy_context": mechanism_taxonomy_context,
            "proxy_template_context": "Do not perform proxy mapping in this stage.",
        },
        "required_fields": [
            "core_idea",
            "structured_summary",
            "seed_factors",
            "hf_factor_points",
            "paper_hf_factors",
            "score_dimensions",
            "recommendation_score",
        ],
        "paper_hf_factor_count": "0-2",
        "compact_output_rules": {
            "core_idea_max_chars": 220,
            "structured_summary_value_max_chars": 180,
            "seed_factors_count": "1-3; at least one kind=faithful_seed_factor",
            "seed_factor_text_max_chars": 260,
            "hf_factor_points_count": 2,
            "paper_hf_factor_count": "0-2; do not pad with non-actionable formulas",
            "factor_text_field_max_chars": 360,
            "score_comment_max_chars": 120,
            "score_evidence_max_chars": 120,
            "score_critique_max_chars": 120,
        },
        "score_dimension_schema": {
            key: {"score": "integer 1-10", "comment": "non-empty Chinese string", "evidence": "non-empty reading_note reference", "critique": "non-empty Chinese string"}
            for key in ("relevance", "mechanism", "statistical", "implementation", "cost_sensitivity", "generality")
        },
        "paper_hf_factor_required_non_empty_fields": [
            "name",
            "mechanism_formula",
            "meaning",
            "paper_mechanism",
            "source_evidence",
            "formula_source_type",
            "formula_source_quote",
            "formula_role_in_paper",
            "why_this_formula_is_actionable",
            "whole_paper_formula",
            "whole_paper_basis",
            "novelty_reason",
            "classic_baseline",
            "minimum_data_needed",
        ],
        "output_json_skeleton": {
            "schema_version": LLM_ANALYSIS_SCHEMA,
            "core_idea": "一句话",
            "structured_summary": {
                "problem": "短句",
                "method": "短句",
                "data": "短句",
                "author_claim": "短句",
                "limitations": "短句",
                "critical_assessment": "短句",
                "missing_tests": "短句",
                "key_results": "短句",
            },
            "seed_factors": [
                {
                    "seed_factor_id": "seed_factor_1",
                    "kind": "faithful_seed_factor/formula_extended_seed_factor/mechanism_extended_seed_factor",
                    "idea": "忠于原文的种子因子或基于原文的扩展种子因子；faithful_seed_factor不必是公式",
                    "faithfulness_anchor": "reading_note引用；必须能复核到原文问题/方法/变量/结果/限制",
                    "extension_boundary": "faithful_seed_factor写'no_extension'；扩展seed_factor写清从原文到发挥的边界",
                    "potential_use": "后续可如何用于字段、状态变量、风险控制或因子设计；不要求本阶段可交易",
                }
            ],
            "hf_factor_points": ["短句1", "短句2"],
            "paper_hf_factors": [
                {
                    "name": "具体机制名",
                    "frequency": "高频/日内/机制推导",
                    "mechanism_category": "other",
                    "mechanism_type": "portfolio_policy",
                    "mechanism_formula": "最终因子公式；可等于文章全文机制公式，也可为结合全文内容创造的mechanism_derived公式；无省略号",
                    "paper_hf_formula_plan": {"template_id": "paper_hf_cost_adjusted_score", "operator_family": "cost_adjusted_optimization", "inputs": [], "windows": [], "normalization": "zscore", "direction": "unknown", "rationale": "短句", "fallback_template": "paper_hf_vol_scaled_return"},
                    "meaning": "短句",
                    "ideal_input_fields": [],
                    "variable_roles": [],
                    "paper_mechanism": "短句",
                    "source_evidence": "reading_note引用",
                    "source_seed_factor_id": "seed_factor_1",
                    "formula_source_type": "final_model_formula/intermediate_definition/estimation_procedure/result_statement/mechanism_derived/llm_proxy_mapping",
                    "formula_source_quote": "支撑公式的原文公式片段或reading_note引用",
                    "formula_role_in_paper": "final_mechanism/setup_definition/calibration_step/robustness_result/empirical_decomposition/proxy_mapping",
                    "why_this_formula_is_actionable": "说明mechanism_formula如何由whole_paper_formula和全文证据推出，并如何成为可行动因子",
                    "whole_paper_formula": "全文机制公式；文章原文最终公式或全文机制综合表达；不是局部定义/校准/估计式",
                    "whole_paper_basis": {"problem": "问题设定引用", "method": "核心方法/模型引用", "final_result_or_formula": "最终公式或关键结果引用", "limitations_or_data": "限制或数据条件引用"},
                    "novelty_reason": "短句",
                    "classic_baseline": "短句",
                    "unobservable_variables": [],
                    "minimum_data_needed": [],
                },
                {
                    "name": "具体机制名",
                    "frequency": "高频/日内/机制推导",
                    "mechanism_category": "other",
                    "mechanism_type": "portfolio_policy",
                    "mechanism_formula": "最终因子公式；可等于文章全文机制公式，也可为结合全文内容创造的mechanism_derived公式；无省略号",
                    "paper_hf_formula_plan": {"template_id": "paper_hf_cost_adjusted_score", "operator_family": "cost_adjusted_optimization", "inputs": [], "windows": [], "normalization": "zscore", "direction": "unknown", "rationale": "短句", "fallback_template": "paper_hf_vol_scaled_return"},
                    "meaning": "短句",
                    "ideal_input_fields": [],
                    "variable_roles": [],
                    "paper_mechanism": "短句",
                    "source_evidence": "reading_note引用",
                    "source_seed_factor_id": "seed_factor_1",
                    "formula_source_type": "final_model_formula/intermediate_definition/estimation_procedure/result_statement/mechanism_derived/llm_proxy_mapping",
                    "formula_source_quote": "支撑公式的原文公式片段或reading_note引用",
                    "formula_role_in_paper": "final_mechanism/setup_definition/calibration_step/robustness_result/empirical_decomposition/proxy_mapping",
                    "why_this_formula_is_actionable": "说明mechanism_formula如何由whole_paper_formula和全文证据推出，并如何成为可行动因子",
                    "whole_paper_formula": "全文机制公式；文章原文最终公式或全文机制综合表达；不是局部定义/校准/估计式",
                    "whole_paper_basis": {"problem": "问题设定引用", "method": "核心方法/模型引用", "final_result_or_formula": "最终公式或关键结果引用", "limitations_or_data": "限制或数据条件引用"},
                    "novelty_reason": "短句",
                    "classic_baseline": "短句",
                    "unobservable_variables": [],
                    "minimum_data_needed": [],
                },
            ],
            "score_dimensions": {
                "relevance": {"score": 1, "comment": "短句", "evidence": "引用", "critique": "短句"},
                "mechanism": {"score": 1, "comment": "短句", "evidence": "引用", "critique": "短句"},
                "statistical": {"score": 1, "comment": "短句", "evidence": "引用", "critique": "短句"},
                "implementation": {"score": 1, "comment": "短句", "evidence": "引用", "critique": "短句"},
                "cost_sensitivity": {"score": 1, "comment": "短句", "evidence": "引用", "critique": "短句"},
                "generality": {"score": 1, "comment": "短句", "evidence": "引用", "critique": "短句"},
            },
            "recommendation_score": 1,
        },
    }
    parsed = copilot_json(prompt=prompt, payload=payload, model=model, copilot_bin=copilot_bin, timeout_sec=timeout_sec, api_key_env=api_key_env)
    structured_summary = _normalize_structured_summary(parsed.get("structured_summary", {}))
    raw_seed_factors = parsed.get("seed_factors", parsed.get("seed_ideas", []))
    seed_factors = raw_seed_factors[:3] if isinstance(raw_seed_factors, list) else []
    has_faithful_seed_factor = any(isinstance(seed, dict) and str(seed.get("kind") or "") in {"faithful_seed_factor", "faithful_seed"} for seed in seed_factors)
    if not has_faithful_seed_factor:
        raise RuntimeError("factor stage output missing faithful seed_factors")
    normalized_factors = normalize_paper_hf_factors(parsed.get("paper_hf_factors", [])[:2])
    paper_hf_factors, dropped_factors = filter_actionable_paper_hf_factors(normalized_factors)
    paper_hf_factors = attach_paper_factor_proxy_analysis(paper_hf_factors)
    score_dimensions = _normalize_dimension_scores(parsed.get("score_dimensions", {}))
    return {
        "core_idea": str(parsed.get("core_idea", ""))[:400],
        "structured_summary": structured_summary,
        "seed_factors": seed_factors,
        "hf_factor_points": [str(x)[:220] for x in parsed.get("hf_factor_points", [])][:4] if isinstance(parsed.get("hf_factor_points"), list) else [],
        "paper_hf_factors": paper_hf_factors,
        "dropped_paper_hf_factors": dropped_factors,
        "factor_candidates": [],
        "score_dimensions": score_dimensions,
        "recommendation_score": _mean_recommendation_score(score_dimensions),
        "analysis_agent": f"paper-three-ai-factor-agent:{model}:{LLM_ANALYSIS_SCHEMA}",
        "analysis_pending_llm": False,
    }


def audit_faithfulness(row: Dict[str, object], reading_note: Dict[str, object], factor_analysis: Dict[str, object], evidence_pack: Dict[str, object], *, model: str, copilot_bin: str, timeout_sec: int, api_key_env: str = "") -> Dict[str, object]:
    prompt = (
        "你是第三阶段忠实度审核模型。检查 paper_hf_factors 是否忠实于 reading_note_v1 和 evidence_pack_v2。"
        "同时检查 seed_factors：至少一个 kind=faithful_seed_factor 必须忠于原文问题、方法、变量、结果或限制；faithful_seed_factor 不必是公式，但必须有可复核的 faithfulness_anchor。"
        "formula_extended_seed_factor/mechanism_extended_seed_factor 可以发挥，但必须清楚说明 extension_boundary，不能伪装成原文直接结论。"
        "重点找：公式篡改、公式来源类型不匹配、把已有结果陈述伪装成可交易因子、未披露样本/统计指标被补造、解释性结论被说成预测 alpha、不可观测变量被伪装成本地字段、交易成本/样本外/容量无证据声称。"
        "逐个检查 formula_source_type、formula_role_in_paper、formula_source_quote 和 why_this_formula_is_actionable：final_model_formula必须能在reading_note/evidence中找到明确最终公式；intermediate_definition/estimation_procedure不能被直接说成可交易因子；result_statement不能被说成作者直接提出的alpha；mechanism_derived/llm_proxy_mapping必须明确标注推导或代理映射。"
        "如果公式只属于setup_definition或calibration_step且没有强连接到最终机制，verdict应为unsupported或partially_faithful并要求重写。"
        "逐个因子给 verdict: faithful/partially_faithful/unsupported/hallucinated，并给 required_revision。"
        "输出 schema_version='faithfulness_audit_v1'。"
    )
    compact_reading_note = {k: v for k, v in reading_note.items() if k != "chunk_notes"}
    compact_factor_analysis = {
        "core_idea": factor_analysis.get("core_idea"),
        "seed_factors": factor_analysis.get("seed_factors") or factor_analysis.get("seed_ideas"),
        "paper_hf_factors": factor_analysis.get("paper_hf_factors"),
        "score_dimensions": factor_analysis.get("score_dimensions"),
        "recommendation_score": factor_analysis.get("recommendation_score"),
    }
    evidence_pack_v2 = build_evidence_pack_v2(evidence_pack)
    compact_evidence = {
        "quality": evidence_pack_v2.get("quality"),
        "missing_evidence": evidence_pack_v2.get("missing_evidence"),
        "excluded_sections": evidence_pack_v2.get("excluded_sections"),
    }
    payload = {
        "article_meta": {
            "title": row.get("title"),
            "url": row.get("url"),
        },
        "reading_note": compact_reading_note,
        "factor_analysis": compact_factor_analysis,
        "evidence_pack_v2_compact": compact_evidence,
        "required_schema": {
            "schema_version": "faithfulness_audit_v1",
            "overall_verdict": "pass/revise/fail",
            "seed_factor_audits": [],
            "factor_audits": [],
            "missing_evidence_violations": [],
            "recommended_action": "accept/rewrite/drop",
        },
    }
    audit = copilot_json(prompt=prompt, payload=payload, model=model, copilot_bin=copilot_bin, timeout_sec=timeout_sec, api_key_env=api_key_env)
    audit.setdefault("schema_version", "faithfulness_audit_v1")
    return audit


def upsert_row(path: Path, row: Dict[str, object]) -> None:
    rows = read_jsonl_valid(path)
    key = str(row.get("dedup_key") or row.get("url") or row.get("title") or "")
    out: List[Dict[str, object]] = []
    replaced = False
    for existing in rows:
        existing_key = str(existing.get("dedup_key") or existing.get("url") or existing.get("title") or "")
        if key and existing_key == key:
            out.append(row)
            replaced = True
        else:
            out.append(existing)
    if not replaced:
        out.insert(0, row)
    write_jsonl(path, out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper pipeline: reading note, generic graph research analysis, deterministic validation.")
    parser.add_argument("--project-root", default=str(ROOT))
    parser.add_argument("--evidence-archive", default="data/arxiv_evidence_archive.jsonl")
    parser.add_argument("--reading-model", default=os.environ.get("PAPER_READING_LLM_MODEL", "gpt-4.1"))
    parser.add_argument("--factor-model", default=os.environ.get("PAPER_FACTOR_LLM_MODEL", "gpt-4.1"))
    parser.add_argument("--reading-key-env", default=os.environ.get("PAPER_READING_LLM_KEY_ENV", ""), help="Environment variable that supplies the reading-stage API key.")
    parser.add_argument("--factor-key-env", default=os.environ.get("PAPER_FACTOR_LLM_KEY_ENV", ""), help="Environment variable that supplies the factor-stage API key.")
    parser.add_argument("--copilot-bin", default=os.environ.get("PAPER_COPILOT_BIN", "copilot"))
    parser.add_argument("--arxiv-id", default="", help="Select a trusted evidence row by arXiv id instead of the latest row.")
    parser.add_argument("--title-contains", default="", help="Select a trusted evidence row whose title contains this text.")
    parser.add_argument("--timeout-sec", type=int, default=int(os.environ.get("PAPER_THREE_AI_TIMEOUT_SEC", "300")))
    parser.add_argument("--chunked-reading", action=argparse.BooleanOptionalAction, default=os.environ.get("PAPER_CHUNKED_READING", "1") == "1")
    parser.add_argument("--single-call-chunked-reading", action=argparse.BooleanOptionalAction, default=os.environ.get("PAPER_SINGLE_CALL_CHUNKED_READING", "0") == "1")
    parser.add_argument("--min-reading-score", type=float, default=float(os.environ.get("PAPER_MIN_READING_SCORE", "5.5")))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    evidence_rows = read_jsonl_valid(root / args.evidence_archive)
    row, evidence_pack = select_trusted_evidence(evidence_rows, arxiv_id=args.arxiv_id, title_contains=args.title_contains)
    started = time.time()
    if args.single_call_chunked_reading:
        reading_note = build_reading_note_single_call_chunked(row, evidence_pack, model=args.reading_model, copilot_bin=args.copilot_bin, timeout_sec=args.timeout_sec, api_key_env=args.reading_key_env)
    elif args.chunked_reading:
        reading_note = build_reading_note_chunked(row, evidence_pack, model=args.reading_model, copilot_bin=args.copilot_bin, timeout_sec=args.timeout_sec, api_key_env=args.reading_key_env)
    else:
        reading_note = build_reading_note(row, evidence_pack, model=args.reading_model, copilot_bin=args.copilot_bin, timeout_sec=args.timeout_sec, api_key_env=args.reading_key_env)
    reading_score = reading_note_score(reading_note)
    if reading_score < args.min_reading_score:
        out = dict(row)
        out["llm_reading_note"] = reading_note
        out["analysis_pipeline"] = "three-ai-reading-gated-v1"
        out["analysis_agent"] = f"paper-reading-gate-agent:{args.reading_model}:reading_note_v1"
        out["analysis_pending_llm"] = True
        out["analysis_error"] = f"reading_score_below_threshold:{reading_score}<{args.min_reading_score}"
        out["score_dimensions"] = _normalize_dimension_scores(reading_note.get("score_dimensions", {}))
        out["recommendation_score"] = reading_score
        out["article_opinions"] = {
            "schema_version": OPINION_ANALYSIS_SCHEMA,
            "article_opinions": [],
            "research_contributions": [],
            "relation_candidates": [],
            "research_ideas": [],
            "status": "gated_by_reading_score",
        }
        out["research_contributions"] = []
        out["relation_candidates"] = []
        out["research_ideas"] = []
        out["factor_candidates"] = []
        out["llm_input_evidence_pack"] = evidence_pack
        out["llm_input_evidence_pack_v2"] = build_evidence_pack_v2(evidence_pack)
        out["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not args.dry_run:
            upsert_row(root / "data" / "analysis_archive.jsonl", out)
            upsert_row(root / "data" / "latest.jsonl", out)
            (root / "data" / "latest_three_ai_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "status": "gated",
            "title": out.get("title"),
            "reading_score": reading_score,
            "min_reading_score": args.min_reading_score,
            "single_call_chunked_reading": args.single_call_chunked_reading,
            "dry_run": args.dry_run,
            "elapsed_sec": round(time.time() - started, 1),
        }, ensure_ascii=False))
        return
    opinion_analysis = generate_article_opinions(
        row,
        reading_note,
        build_evidence_pack_v2(evidence_pack),
        copilot_json=copilot_json,
        model=args.factor_model,
        copilot_bin=args.copilot_bin,
        timeout_sec=args.timeout_sec,
        api_key_env=args.factor_key_env,
    )
    out = dict(row)
    out["article_opinions"] = opinion_analysis
    out["research_contributions"] = list(opinion_analysis.get("research_contributions") or [])
    out["relation_candidates"] = list(opinion_analysis.get("relation_candidates") or [])
    out["research_ideas"] = list(opinion_analysis.get("research_ideas") or [])
    out["analysis_validation"] = dict(opinion_analysis.get("analysis_validation") or {})
    out["llm_audit_status"] = "not_run_not_required"
    out["llm_reading_note"] = reading_note
    out["reading_recommendation_score"] = reading_score
    out["llm_opinion_analysis_input"] = {
        "reading_note_schema_version": reading_note.get("schema_version"),
        "opinion_model": args.factor_model,
    }
    out["llm_input_evidence_pack"] = evidence_pack
    out["llm_input_evidence_pack_v2"] = build_evidence_pack_v2(evidence_pack)
    out["analysis_pipeline"] = "paper-reading-generic-research-v2"
    out["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not args.dry_run:
        upsert_row(root / "data" / "analysis_archive.jsonl", out)
        upsert_row(root / "data" / "latest.jsonl", out)
        (root / "data" / "latest_three_ai_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "status": "ok",
        "title": out.get("title"),
        "url": out.get("url"),
        "pipeline": out.get("analysis_pipeline"),
        "reading_model": args.reading_model,
        "factor_model": args.factor_model,
        "reading_key_env": args.reading_key_env or None,
        "factor_key_env": args.factor_key_env or None,
        "chunked_reading": args.chunked_reading,
        "single_call_chunked_reading": args.single_call_chunked_reading,
        "contribution_count": len(out.get("research_contributions") or []),
        "idea_count": len(out.get("research_ideas") or []),
        "validation_status": (out.get("analysis_validation") or {}).get("status"),
        "dry_run": args.dry_run,
        "elapsed_sec": round(time.time() - started, 1),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
