#!/usr/bin/env python3
"""Render opinion analyses as paper modules, mirroring the factor dashboard layout."""
from __future__ import annotations

import html
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm.three_ai.pipeline import RESEARCH_TOPIC_LABELS, infer_research_topic_category  # noqa: E402


def esc(value: object, fallback: str = "未披露") -> str:
    text = str(value).strip() if value is not None else ""
    return html.escape(text or fallback)


def field(label: str, value: object) -> str:
    return f"<div class='field'><strong>{esc(label)}</strong><div>{esc(value)}</div></div>"


def render_paper(payload: dict) -> str:
    analysis = payload.get("article_opinions") if isinstance(payload.get("article_opinions"), dict) else {}
    opinions = [item for item in analysis.get("article_opinions", []) if isinstance(item, dict)]
    validation = payload.get("analysis_validation") if isinstance(payload.get("analysis_validation"), dict) else analysis.get("analysis_validation") if isinstance(analysis.get("analysis_validation"), dict) else {}
    verdict = validation.get("status") or "未校验"
    contributions = payload.get("research_contributions") if isinstance(payload.get("research_contributions"), list) else analysis.get("research_contributions") if isinstance(analysis.get("research_contributions"), list) else []
    category = analysis.get("opinion_category") or (analysis.get("opinion_classification") or {}).get("selected_agent") or "未分类"
    reading_note = payload.get("llm_reading_note") if isinstance(payload.get("llm_reading_note"), dict) else {}
    topic = reading_note.get("research_topic_category") or payload.get("research_topic_category") or infer_research_topic_category(payload, reading_note)
    topic_label = RESEARCH_TOPIC_LABELS.get(str(topic), str(topic))
    publication_date = payload.get("published_at") or payload.get("publication_date") or payload.get("published") or ""
    completed = "1" if payload.get("analysis_pending_llm") is False else "0"
    title = payload.get("title") or ("Temporal Fusion Transformer for Interpretable Multi-horizon Time Series Forecasting" if str(payload.get("arxiv_id")) == "1912.09363" else "")
    title = title or f"arXiv {payload.get('arxiv_id') or '未命名论文'}"
    url = payload.get("url") or (f"https://arxiv.org/abs/{payload.get('arxiv_id')}" if payload.get("arxiv_id") else "#")
    summary = analysis.get("structured_summary") if isinstance(analysis.get("structured_summary"), dict) else {}
    labels = {"problem":"研究问题", "method":"方法", "author_claim":"作者主张", "evidence_status":"证据状态", "limitations":"局限", "critical_assessment":"批判性评估", "missing_tests":"缺失验证", "datasets":"数据集与预测任务", "metrics_explained":"指标与损失解释", "experiment_details":"实验设置", "plain_language_takeaway":"通俗总结"}
    summary_html = "".join(field(labels.get(str(k), str(k)), v) for k, v in summary.items() if v)
    agent = analysis.get("selected_opinion_agent") or category
    model = analysis.get("analysis_agent") or "未披露"
    cards = []
    for i, item in enumerate(opinions, 1):
        text = " ".join(str(item.get(k, "")) for k in ("claim", "assessment", "supporting_evidence", "evidence_anchor", "limitations", "dataset_details", "metric_explanation"))
        cards.append("<article class='idea-card' data-search='" + esc(text) + "' data-confidence='" + esc(item.get("confidence")) + "'><div class='card-head'><span class='pill'>" + esc(item.get("idea_category") or category) + "</span><span class='type'>Idea " + str(i) + " · " + esc(item.get("confidence")) + "</span></div>" + field("想法主张", item.get("claim")) + field("分析判断（通俗解释）", item.get("assessment")) + field("支持证据", item.get("supporting_evidence")) + field("证据锚点", item.get("evidence_anchor")) + field("数据集细节", item.get("dataset_details")) + field("指标与损失解释", item.get("metric_explanation")) + field("局限与待验证内容", item.get("limitations")) + "</article>")
    cards_html = "".join(cards) or "<div class='empty'>当前材料不足以提出可复查的研究想法。</div>"
    status_class = "revise" if verdict == "pass_with_warnings" else "fail" if verdict == "reject" else ""
    paper_search = title + " " + str(payload.get("arxiv_id") or "") + " " + " ".join(str(v) for v in summary.values())
    return "<article class='paper-module' data-search='" + esc(paper_search) + "' data-verdict='" + esc(verdict) + "' data-category='" + esc(category) + "' data-topic='" + esc(topic) + "' data-recommendation='" + esc(analysis.get("recommendation_score") or reading_note.get("recommendation_score")) + "' data-completed='" + completed + "' data-date='" + esc(publication_date, "") + "' data-arxiv='" + esc(payload.get("arxiv_id"), "") + "'><div class='paper-head'><div><h2><a href='" + esc(url) + "' target='_blank' rel='noopener'>" + esc(title) + " ↗</a></h2><div class='meta'>arXiv: " + esc(payload.get("arxiv_id")) + " · " + esc(payload.get("source_name"), "arXiv") + "</div></div><span class='status " + status_class + "'>确定性校验：" + esc(verdict) + "</span></div><div class='paper-meta'><span class='pill'>研究主题：" + esc(topic_label) + "</span><span class='pill'>分析模式：" + esc(agent) + "</span><span class='pill'>AI：" + esc(model) + "</span><span class='pill'>论文贡献：" + str(len(contributions)) + " 条</span><span class='pill'>研究想法：" + str(len(opinions)) + " 条</span></div><div class='paper-grid'><section class='paper-summary'><h3>论文摘要与实验信息</h3><div class='meta-grid'><div class='meta'><b>分析流水线</b>" + esc(payload.get("analysis_pipeline")) + "</div><div class='meta'><b>推荐分</b>" + esc(analysis.get("recommendation_score") or reading_note.get("recommendation_score")) + "</div></div>" + (summary_html or "<div class='empty'>暂无结构化摘要</div>") + "</section><section><h3>研究想法与证据解释</h3><div class='ideas'>" + cards_html + "</div></section></div></article>"


def read_archive(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("arxiv_id"):
            rows.append(row)
    return rows


def merge_archives(paths: list[Path], keep_duplicates: bool = False) -> list[dict]:
    if keep_duplicates:
        rows_out = []
        for path in paths:
            for row in read_archive(path):
                if row.get("status") == "failed":
                    continue
                analysis = row.get("article_opinions") if isinstance(row.get("article_opinions"), dict) else {}
                model = str(row.get("model") or row.get("analysis_agent") or analysis.get("analysis_agent") or "")
                if model and model not in {"gpt-5.4-mini", "gpt-5-mini"} and "gpt-5.4-mini" not in model and "gpt-5-mini" not in model:
                    continue
                rows_out.append(row)
        return rows_out

    merged: dict[str, dict] = {}
    for path in paths:
        for row in read_archive(path):
            if row.get("status") == "failed":
                continue
            analysis = row.get("article_opinions") if isinstance(row.get("article_opinions"), dict) else {}
            model = str(row.get("model") or row.get("analysis_agent") or analysis.get("analysis_agent") or "")
            # The dashboard is for the current Copilot-p runs.  Legacy gpt-4o
            # and gpt-4o-mini rows remain in their source archives but are not
            # mixed into this page.
            if model and model not in {"gpt-5.4-mini", "gpt-5-mini"} and "gpt-5.4-mini" not in model and "gpt-5-mini" not in model:
                continue
            key = str(row.get("arxiv_id") or row.get("title") or "").strip().lower()
            if key:
                merged[key] = row
    return list(merged.values())


def main() -> None:
    configured = os.environ.get("PAPER_OPINION_ARCHIVES", "")
    if configured:
        archive_paths = [Path(item) for item in configured.split(os.pathsep) if item]
    else:
        archive_paths = [
            ROOT / "data" / "opinion_analysis_archive.jsonl",
            ROOT / "data" / "opinion_batch_analysis_gpt54mini_20260724.jsonl",
            ROOT / "data" / "arxiv_tex_three_ai_analysis.jsonl",
        ]
    archive_paths = [path if path.is_absolute() else ROOT / path for path in archive_paths]
    keep_duplicates = os.environ.get("PAPER_OPINION_KEEP_DUPLICATES", "").lower() in {"1", "true", "yes"}
    payloads = merge_archives(archive_paths, keep_duplicates=keep_duplicates)
    if not payloads:
        batch_source = ROOT / "data" / "opinion_batch_latest_20260723.json"
        source = batch_source if batch_source.exists() else ROOT / "data" / "latest_opinion_digest.json"
        if source.exists():
            payload = json.loads(source.read_text(encoding="utf-8"))
            payloads = [payload] if isinstance(payload, dict) else []
    target = ROOT / "public" / "opinion_digest.html"
    paper_html = "".join(render_paper(payload) for payload in payloads)
    style = ":root{color-scheme:dark}body{font-family:Inter,Arial,'Microsoft YaHei',sans-serif;background:#0b1020;color:#e8ecf1;margin:0}.wrap{max-width:1200px;margin:0 auto;padding:24px}.hero{padding:18px 20px;border-radius:14px;background:linear-gradient(135deg,#1d2b64,#4b6cb7)}.hero h1{margin:0 0 8px;font-size:28px}.muted,.meta{color:#9eb0c9}.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.pill,.status{display:inline-block;border-radius:999px;padding:6px 12px;font-size:12px;font-weight:800;background:#174533;color:#9df2c1;border:1px solid #2d825c}.status.revise{background:#493b18;color:#ffdb86;border-color:#806929}.status.fail{background:#4a2535;color:#ffadc2;border-color:#82445a}.search-panel,.paper-module{margin-top:16px;background:#131a2d;border:1px solid #26314d;border-radius:12px;padding:14px}.search-row{display:flex;gap:8px;margin-top:10px}.search-row input,.search-row select{box-sizing:border-box;background:#0f1528;border:1px solid #2a3552;border-radius:8px;color:#e8ecf1;padding:10px}.search-row input{flex:1}.search-row button{background:#1d3a2f;border:1px solid #35a969;color:#9ff6c4;border-radius:8px;padding:0 12px}.result-count{color:#9eb0c9;font-size:12px;margin-top:8px}.paper-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}.paper-head h2{margin:0 0 7px;font-size:21px}.paper-head a{color:#80b3ff;text-decoration:none}.paper-head a:hover{text-decoration:underline}.paper-meta{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.paper-grid{display:grid;grid-template-columns:1fr 1.55fr;gap:16px}.paper-summary,.ideas{background:#0f1528;border:1px solid #2a3552;border-radius:10px;padding:12px}.paper-grid h3{margin:0 0 9px;font-size:16px}.meta-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px}.meta{background:#111a30;border:1px solid #253250;border-radius:8px;padding:8px;font-size:12px}.meta b{display:block;color:#9fc5ff;margin-bottom:4px}.field{padding:10px 0;border-bottom:1px solid #243650;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}.field strong{display:block;color:#9fc5ff;font-size:12px;margin-bottom:4px}.idea-card{background:#111a30;border:1px solid #253250;border-radius:9px;padding:12px;margin-bottom:10px}.idea-card:last-child{margin-bottom:0}.card-head{display:flex;justify-content:space-between;gap:8px}.type{color:#a8b8cd;font-size:12px}.empty{padding:24px;text-align:center;color:#a8b8cd;border:1px dashed #3a4e6e;border-radius:8px}@media(max-width:850px){.paper-grid,.meta-grid{grid-template-columns:1fr}.paper-head{display:block}}"
    script = "<script>const q=document.querySelector('#paper-search'),sort=document.querySelector('#paper-sort'),list=document.querySelector('#paper-list'),count=document.querySelector('#paper-count');function verdictRank(v){return v==='pass'?0:v==='pass_with_warnings'?1:v==='reject'?2:3}function num(v){const n=Number.parseFloat(v);return Number.isFinite(n)?n:-1}function apply(){const term=q.value.toLowerCase().trim(),items=[...list.querySelectorAll('.paper-module')];items.forEach(x=>x.hidden=term&&!x.dataset.search.toLowerCase().includes(term));if(sort.value==='pass-score'){items.sort((a,b)=>a.dataset.category.localeCompare(b.dataset.category)||verdictRank(a.dataset.verdict)-verdictRank(b.dataset.verdict)||num(b.dataset.recommendation)-num(a.dataset.recommendation)||Number(b.dataset.completed)-Number(a.dataset.completed)||b.dataset.date.localeCompare(a.dataset.date)||a.dataset.arxiv.localeCompare(b.dataset.arxiv)).forEach(x=>list.appendChild(x));}else if(sort.value==='revise'){items.sort((a,b)=>(b.dataset.verdict==='pass_with_warnings')-(a.dataset.verdict==='pass_with_warnings')).forEach(x=>list.appendChild(x));}count.textContent=items.filter(x=>!x.hidden).length+' / '+items.length+' 篇论文'}q.addEventListener('input',apply);sort.addEventListener('change',apply);function clearSearch(){q.value='';apply()}apply();</script>"
    doc = "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Paper Research Digest</title><style>" + style + "</style></head><body><main class='wrap'><header class='hero'><h1>论文 Research Digest</h1><div class='muted'>按论文组织贡献、研究想法、摘要、证据和确定性校验结果</div><div class='toolbar'><span class='pill'>论文模块</span><span class='pill'>支持搜索 / 筛选 / 排序</span></div></header><section class='search-panel'><strong>Paper Digest <span class='muted'>search / filter / rank</span></strong><div class='search-row'><input id='paper-search' type='search' placeholder='搜索论文标题 / arXiv ID / 证据…'><select id='paper-sort'><option value='default'>默认顺序</option><option value='pass-score'>校验通过优先 + 推荐度</option><option value='revise'>优先显示带警告论文</option></select><button onclick='clearSearch()'>清除</button></div><div id='paper-count' class='result-count'></div></section><section id='paper-list'>" + paper_html + "</section></main>" + script + "</body></html>"
    target.write_text(doc, encoding="utf-8")
    print(json.dumps({"status":"ok","output":str(target),"paper_count":len(payloads)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
