#!/usr/bin/env python3
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def compact(value: object, limit: int = 1800) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def badge_class(verdict: object) -> str:
    value = str(verdict or "").lower()
    if value in {"faithful", "pass", "accept"} or "faithful" in value:
        return "ok"
    if value in {"fail", "reject", "drop"} or "fail" in value or "reject" in value:
        return "bad"
    return "warn"


def final_use_status(verdict: object) -> str:
    value = str(verdict or "").strip().lower()
    if value in {"faithful", "pass", "accept", "accepted", "usable"}:
        return "usable"
    if value in {"reject", "rejected", "fail", "drop", "hallucinated", "unsupported"}:
        return "rejected"
    return "needs_revision"


def factor_id(row: dict[str, Any], index: int) -> str:
    base = str(row.get("dedup_key") or row.get("url") or row.get("title") or "three_ai_factor")
    safe = "".join(ch if ch.isalnum() else "_" for ch in base.lower()).strip("_")[:80]
    return f"{safe}:{index}"


def row_faithfulness_identity(row: dict[str, Any], index: int) -> str:
    dedup = str(row.get("dedup_key") or "").strip()
    if dedup:
        return f"{dedup}:{index}"
    url = str(row.get("url") or "").strip()
    if url:
        return f"url:{url}:{index}"
    return factor_id(row, index)


def load_human_reviews(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    reviews = payload.get("reviews") if isinstance(payload, dict) else {}
    return {str(key): value for key, value in reviews.items() if isinstance(value, dict)} if isinstance(reviews, dict) else {}


def audit_for_factor(audit: dict[str, Any], factor: dict[str, Any]) -> dict[str, Any]:
    name = str(factor.get("name") or "")
    audits = audit.get("factor_audits") if isinstance(audit.get("factor_audits"), list) else []
    for item in audits:
        if isinstance(item, dict) and str(item.get("factor_name") or item.get("name") or "") == name:
            return item
    return {}


def build_records(row: dict[str, Any], human_reviews: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    factors = row.get("paper_hf_factors") if isinstance(row.get("paper_hf_factors"), list) else []
    faithfulness = row.get("llm_faithfulness_audit") if isinstance(row.get("llm_faithfulness_audit"), dict) else {}
    records: list[dict[str, Any]] = []
    for index, factor in enumerate(factors):
        if not isinstance(factor, dict):
            continue
        llm_audit = audit_for_factor(faithfulness, factor)
        local_id = factor_id(row, index)
        render_id = row_faithfulness_identity(row, index)
        human_review = human_reviews.get(render_id) or human_reviews.get(local_id) or {}
        final_verdict = human_review.get("verdict") or llm_audit.get("verdict") or "needs_review"
        records.append(
            {
                "factor_id": render_id,
                "local_factor_id": local_id,
                "index": index,
                "article": {"title": row.get("title"), "url": row.get("url")},
                "title": row.get("title"),
                "url": row.get("url"),
                "analysis_pipeline": row.get("analysis_pipeline"),
                "factor": factor,
                "reading_note": row.get("llm_reading_note") if isinstance(row.get("llm_reading_note"), dict) else {},
                "evidence_pack_v2": row.get("llm_input_evidence_pack_v2") if isinstance(row.get("llm_input_evidence_pack_v2"), dict) else {},
                "llm_faithfulness_review": llm_audit,
                "human_review": human_review,
                "final_verdict": final_verdict,
                "final_use_status": final_use_status(final_verdict),
                "overall_verdict": faithfulness.get("overall_verdict"),
                "recommended_action": faithfulness.get("recommended_action"),
                "missing_evidence_violations": faithfulness.get("missing_evidence_violations", []),
            }
        )
    return records


def render_html(row: dict[str, Any], records: list[dict[str, Any]]) -> str:
    dropped_factors = row.get("dropped_paper_hf_factors") if isinstance(row.get("dropped_paper_hf_factors"), list) else []
    dropped_html = f"<section class=\"toolbar\"><strong>已过滤中间推导/校准项：</strong>{len(dropped_factors)} 个</section>" if dropped_factors else ""
    verdicts = sorted({str(r.get("llm_faithfulness_review", {}).get("verdict") or "needs_review") for r in records})
    cards: list[str] = []
    for record in records:
        factor = record["factor"]
        review = record.get("llm_faithfulness_review") if isinstance(record.get("llm_faithfulness_review"), dict) else {}
        human_review = record.get("human_review") if isinstance(record.get("human_review"), dict) else {}
        verdict = str(review.get("verdict") or "needs_review")
        human_verdict = str(human_review.get("verdict") or "未审核")
        use_status = str(record.get("final_use_status") or "needs_revision")
        final_proxy = {
            "formula_plan": factor.get("paper_hf_formula_plan"),
            "proxy_mappings": factor.get("proxy_mappings"),
            "ideal_input_fields": factor.get("ideal_input_fields"),
            "minimum_data_needed": factor.get("minimum_data_needed"),
        }
        formula_source = {
            "mechanism_formula": factor.get("mechanism_formula"),
            "whole_paper_formula": factor.get("whole_paper_formula"),
            "whole_paper_basis": factor.get("whole_paper_basis"),
            "formula_source_type": factor.get("formula_source_type"),
            "formula_source_quote": factor.get("formula_source_quote"),
            "formula_role_in_paper": factor.get("formula_role_in_paper"),
            "why_this_formula_is_actionable": factor.get("why_this_formula_is_actionable"),
            "source_evidence": factor.get("source_evidence"),
        }
        article_input = {
            "title": record.get("title"),
            "url": record.get("url"),
            "central_claim": record.get("reading_note", {}).get("central_claim"),
            "problem": record.get("reading_note", {}).get("problem"),
            "score_dimensions": record.get("reading_note", {}).get("score_dimensions"),
            "recommendation_score": record.get("reading_note", {}).get("recommendation_score"),
        }
        cards.append(
            f"""
<article class="card" data-factor-id="{esc(record['factor_id'])}" data-verdict="{esc(verdict)}" data-title="{esc(str(record.get('title') or '').lower())}">
    <div class="card-head">
        <div><h2>{esc(factor.get('name'))}</h2><div class="meta"><code>{esc(record['factor_id'])}</code> | {esc(record.get('analysis_pipeline'))}</div><div>{esc(record.get('title'))}</div></div>
        <div class="badge-row"><span class="badge {badge_class(verdict)}">LLM：{esc(verdict)}</span><span class="badge {badge_class(human_verdict)}" data-human-label>人工：{esc(human_verdict)}</span><span class="badge {badge_class(record.get('overall_verdict'))}">整体：{esc(record.get('overall_verdict'))}</span><span class="badge {badge_class(use_status)}">使用：{esc(use_status)}</span></div>
    </div>
    <section class="review-actions" data-review-actions>
        <strong>人工审核</strong>
        <button data-verdict="faithful">faithful</button>
        <button data-verdict="translated">translated</button>
        <button data-verdict="exploratory">exploratory</button>
        <button data-verdict="reject">reject</button>
        <button data-verdict="needs_review">needs_review</button>
        <input data-reviewer placeholder="reviewer" value="{esc(human_review.get('reviewer'))}">
        <input data-score placeholder="score" value="{esc(human_review.get('score'))}">
        <textarea data-notes placeholder="审核备注：机制是否忠实、公式是否过度代理、是否可进入下一步">{esc(human_review.get('notes'))}</textarea>
        <span class="review-state" data-review-state>{'已从服务端人工审核 JSON 加载' if human_review else '未保存到本地'}</span>
    </section>
    <section class="grid">
        <div class="block"><h3>文章输入 / 第一阶段评分</h3><pre>{esc(json.dumps(article_input, ensure_ascii=False, indent=2))}</pre></div>
        <div class="block"><h3>AI 原始因子输出</h3><pre>{esc(json.dumps(factor, ensure_ascii=False, indent=2))}</pre></div>
        <div class="block"><h3>公式来源判定</h3><pre>{esc(json.dumps(formula_source, ensure_ascii=False, indent=2))}</pre></div>
        <div class="block"><h3>最终可计算代理 / 映射</h3><pre>{esc(json.dumps(final_proxy, ensure_ascii=False, indent=2))}</pre></div>
        <div class="block"><h3>LLM 忠实度审核</h3><p><b>verdict：</b>{esc(verdict)}</p><p><b>required_revision：</b>{esc(compact(review.get('required_revision'), 1200))}</p><pre>{esc(json.dumps(review, ensure_ascii=False, indent=2))}</pre></div>
    </section>
</article>"""
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HF 忠实性人工审核台</title>
<style>
:root {{ --bg:#f7f4ec; --ink:#1f2933; --muted:#68737d; --line:#d8d1c2; --ok:#0b7a53; --warn:#a65f00; --bad:#9f2d2d; --card:#fffdf7; --soft:#f3eee2; }}
* {{ box-sizing:border-box; }} body {{ margin:0; font-family:ui-sans-serif,system-ui,sans-serif; color:var(--ink); background:linear-gradient(135deg,#f7f4ec,#eef4f1); }}
header {{ padding:28px 36px 18px; border-bottom:1px solid var(--line); }} main {{ max-width:1280px; margin:0 auto; padding:20px 24px 44px; }}
h1 {{ margin:0 0 8px; font-size:28px; }} h2 {{ margin:0; font-size:18px; }} h3 {{ margin:0 0 10px; font-size:15px; }} .muted,.meta {{ color:var(--muted); font-size:13px; }}
.summary {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; margin-bottom:14px; }} .stat,.card,.toolbar,.block {{ background:var(--card); border:1px solid var(--line); border-radius:8px; box-shadow:0 10px 24px rgba(55,47,31,.06); }} .stat {{ padding:14px; }} .stat b {{ display:block; font-size:24px; }}
.toolbar {{ display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:12px; margin:14px 0; position:sticky; top:0; z-index:2; }} input,select,textarea,button {{ border:1px solid var(--line); border-radius:7px; padding:7px 9px; background:#fff; color:var(--ink); }} textarea {{ width:min(460px,100%); min-height:42px; vertical-align:top; }} button {{ cursor:pointer; }} button.active {{ border-color:rgba(11,122,83,.45); background:#eef8f3; color:var(--ok); font-weight:800; }}
.card {{ padding:16px; margin-bottom:14px; }} .card-head {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }} .badge-row {{ display:flex; flex-wrap:wrap; gap:6px; }} .badge,.chip {{ border:1px solid var(--line); border-radius:999px; padding:4px 8px; font-size:12px; background:#fff; }} .badge.ok {{ border-color:rgba(11,122,83,.35); color:var(--ok); background:#eef8f3; }} .badge.warn {{ border-color:rgba(166,95,0,.35); color:var(--warn); background:#fff7e8; }} .badge.bad {{ border-color:rgba(159,45,45,.35); color:var(--bad); background:#fff0ef; }}
.grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:12px; }} .block {{ padding:12px; overflow:auto; }} pre {{ white-space:pre-wrap; font-size:12px; background:var(--soft); padding:10px; border-radius:7px; overflow:auto; max-height:560px; }} code {{ background:var(--soft); border-radius:5px; padding:1px 4px; }} .review-actions {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; padding:10px; margin:12px 0; border:1px solid var(--line); border-radius:8px; background:#fff; }} .review-state {{ color:var(--muted); font-size:12px; }}
@media (max-width:900px) {{ .grid {{ grid-template-columns:1fr; }} .card-head {{ flex-direction:column; }} }}
</style>
<script>
const KEY='hf_factor_faithfulness_reviews_v1';
function loadReviews(){{try{{return JSON.parse(localStorage.getItem(KEY)||'{{}}')}}catch(e){{return {{}}}}}}
function saveReviews(v){{localStorage.setItem(KEY,JSON.stringify(v));}}
function applyFilters(){{const q=document.getElementById('q').value.toLowerCase();const verdict=document.getElementById('verdict').value;let shown=0;document.querySelectorAll('.card').forEach(c=>{{const okQ=!q||c.dataset.title.includes(q)||c.dataset.factorId.toLowerCase().includes(q);const okV=!verdict||c.dataset.verdict===verdict;const show=okQ&&okV;c.style.display=show?'':'none';if(show)shown++;}});document.getElementById('shown').textContent=shown;}}
function refreshReviews(){{const reviews=loadReviews();document.querySelectorAll('.card').forEach(c=>{{const id=c.dataset.factorId;const r=reviews[id]||{{}};const label=c.querySelector('[data-human-label]');if(r.verdict&&label){{label.textContent='人工：'+r.verdict;label.className='badge '+(r.verdict==='faithful'?'ok':r.verdict==='reject'?'bad':'warn');}}c.querySelectorAll('[data-verdict]').forEach(b=>b.classList.toggle('active',b.dataset.verdict===r.verdict));const reviewer=c.querySelector('[data-reviewer]');const score=c.querySelector('[data-score]');const notes=c.querySelector('[data-notes]');const state=c.querySelector('[data-review-state]');if(reviewer&&r.reviewer)reviewer.value=r.reviewer;if(score&&r.score)score.value=r.score;if(notes&&r.notes)notes.value=r.notes;if(state&&r.verdict)state.textContent='已保存在浏览器，可导出 JSON';}});}}
function exportReviews(){{const reviews=loadReviews();const payload={{version:1,exported_at:new Date().toISOString(),reviews}};const blob=new Blob([JSON.stringify(payload,null,2)],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='hf_factor_faithfulness_reviews.json';a.click();URL.revokeObjectURL(a.href);}}
window.addEventListener('DOMContentLoaded',()=>{{document.querySelectorAll('.card').forEach(c=>{{c.querySelectorAll('[data-verdict]').forEach(b=>b.addEventListener('click',()=>{{const reviews=loadReviews();const id=c.dataset.factorId;reviews[id]={{...(reviews[id]||{{}}),verdict:b.dataset.verdict,reviewer:c.querySelector('[data-reviewer]').value,score:c.querySelector('[data-score]').value,notes:c.querySelector('[data-notes]').value,reviewed_at:new Date().toISOString()}};saveReviews(reviews);refreshReviews();}}));c.querySelectorAll('[data-reviewer],[data-score],[data-notes]').forEach(el=>el.addEventListener('change',()=>{{const reviews=loadReviews();const id=c.dataset.factorId;reviews[id]={{...(reviews[id]||{{}}),reviewer:c.querySelector('[data-reviewer]').value,score:c.querySelector('[data-score]').value,notes:c.querySelector('[data-notes]').value,reviewed_at:new Date().toISOString()}};saveReviews(reviews);refreshReviews();}}));}});document.getElementById('q').addEventListener('input',applyFilters);document.getElementById('verdict').addEventListener('change',applyFilters);document.getElementById('export').addEventListener('click',exportReviews);refreshReviews();applyFilters();}});
</script>
</head>
<body>
<header><h1>HF 忠实性人工审核台</h1><div class="muted">逐项核对第一阶段文章理解、第二阶段因子输出和第三阶段 LLM 忠实度审核。人工选择会保存在浏览器 localStorage，可导出 JSON。</div></header>
<main>
<section class="summary"><div class="stat"><span>当前论文</span><b>1</b></div><div class="stat"><span>HF 因子</span><b>{len(records)}</b></div><div class="stat"><span>整体 verdict</span><b>{esc(row.get('faithfulness_verdict'))}</b></div><div class="stat"><span>推荐动作</span><b>{esc((row.get('llm_faithfulness_audit') or {}).get('recommended_action') if isinstance(row.get('llm_faithfulness_audit'), dict) else '')}</b></div></section>
{dropped_html}
<section class="toolbar"><input id="q" placeholder="搜索标题/factor_id"><select id="verdict"><option value="">全部 verdict</option>{''.join(f'<option value="{esc(v)}">{esc(v)}</option>' for v in verdicts)}</select><button id="export">导出人工审核 JSON</button><span class="muted">显示 <b id="shown">0</b> / {len(records)}</span></section>
{''.join(cards)}
</main>
</body>
</html>
"""


def main() -> int:
    row = json.loads((ROOT / "data" / "latest_three_ai_result.json").read_text(encoding="utf-8"))
    human_reviews = load_human_reviews(ROOT / "data" / "hf_factor_faithfulness_reviews.json")
    records = build_records(row, human_reviews)
    audit_payload = {
        "schema_version": "three_ai_hf_factor_faithfulness_audit_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "data/latest_three_ai_result.json",
        "title": row.get("title"),
        "url": row.get("url"),
        "human_reviews_source": "data/hf_factor_faithfulness_reviews.json",
        "records": records,
    }
    faithfulness = row.get("llm_faithfulness_audit") if isinstance(row.get("llm_faithfulness_audit"), dict) else {}
    summary_payload = {
        "latest_three_ai_title": row.get("title"),
        "overall_verdict": row.get("faithfulness_verdict") or faithfulness.get("overall_verdict"),
        "recommended_action": faithfulness.get("recommended_action"),
        "factor_count": len(records),
    }
    llm_review_payload = {
        "schema_version": "three_ai_factor_llm_faithfulness_review_v1",
        "generated_at": audit_payload["generated_at"],
        "source": "data/latest_three_ai_result.json",
        "records": [
            {
                "factor_id": record.get("factor_id"),
                "local_factor_id": record.get("local_factor_id"),
                "factor_index": record.get("index"),
                "title": record.get("title"),
                "url": record.get("url"),
                "model": faithfulness.get("model") or faithfulness.get("review_model"),
                "verdict": (record.get("llm_faithfulness_review") or {}).get("verdict") if isinstance(record.get("llm_faithfulness_review"), dict) else None,
                "score": (record.get("llm_faithfulness_review") or {}).get("score") if isinstance(record.get("llm_faithfulness_review"), dict) else None,
                "rationale": (record.get("llm_faithfulness_review") or {}).get("required_revision") if isinstance(record.get("llm_faithfulness_review"), dict) else None,
                "reason": (record.get("llm_faithfulness_review") or {}).get("required_revision") if isinstance(record.get("llm_faithfulness_review"), dict) else None,
                "overall_verdict": record.get("overall_verdict"),
                "recommended_action": record.get("recommended_action"),
            }
            for record in records
        ],
    }
    reports = ROOT / "reports"
    public = ROOT / "public"
    reports.mkdir(parents=True, exist_ok=True)
    public.mkdir(parents=True, exist_ok=True)
    (reports / "hf_factor_faithfulness_audit.json").write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (reports / "hf_factor_faithfulness_summary.json").write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (reports / "hf_factor_faithfulness_llm_review.json").write_text(json.dumps(llm_review_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_text = render_html(row, records)
    (reports / "hf_factor_faithfulness_audit.html").write_text(html_text, encoding="utf-8")
    (public / "hf_factor_faithfulness_audit.html").write_text(html_text, encoding="utf-8")
    print(json.dumps({"status": "ok", "records": len(records), "html": str(public / "hf_factor_faithfulness_audit.html")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())