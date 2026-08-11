#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline.daily_research_pipeline import (  # noqa: E402
    SITE_INDEX_URL,
    attach_factor_quality_results,
    attach_factor_results,
    attach_paper_hf_large_results,
    attach_paper_hf_medium_results,
    attach_paper_hf_proxy_results,
    build_history,
    collect_archive_rows,
    load_factor_quality_results,
    load_factor_results,
    load_paper_hf_large_results,
    load_paper_hf_medium_results,
    load_paper_hf_proxy_results,
    read_jsonl,
    render_archive_page,
    render_daily_page,
    render_home_page,
)
from src.render.summarize_hf_proxy_diversity import build_summary, inject_dashboard, render_html  # noqa: E402


def _result_field_count(path: Path) -> int:
    if not path.exists():
        return -1
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return -1
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return -1
    return len({str(row.get("factor_field") or "") for row in rows if isinstance(row, dict) and row.get("factor_field")})


def _result_fields(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return set()
    return {str(row.get("factor_field") or "") for row in rows if isinstance(row, dict) and row.get("factor_field")}


def _manifest_fields(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    specs = payload.get("specs", []) if isinstance(payload, dict) else []
    if not isinstance(specs, list):
        return set()
    return {str(item.get("field") or "") for item in specs if isinstance(item, dict) and item.get("field")}


def _load_hf_faithfulness_records(path: Path) -> tuple[dict[str, dict[str, object]], dict[tuple[str, str], dict[str, object]]]:
    if not path.exists():
        return {}, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    records = payload.get("records", []) if isinstance(payload, dict) else []
    by_id: dict[str, dict[str, object]] = {}
    by_title_index: dict[tuple[str, str], dict[str, object]] = {}
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        factor_id = str(record.get("factor_id") or "")
        if factor_id:
            by_id[factor_id] = record
            factor_index = factor_id.rsplit(":", 1)[-1]
        else:
            factor_index = ""
        article = record.get("article") if isinstance(record.get("article"), dict) else {}
        title = str(article.get("title") or record.get("title") or "")
        if title and factor_index:
            by_title_index[(title, factor_index)] = record
    return by_id, by_title_index


def _load_hf_faithfulness_llm_reviews(path: Path) -> tuple[dict[str, dict[str, object]], dict[tuple[str, str], dict[str, object]]]:
    if not path.exists():
        return {}, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    records = payload.get("records", []) if isinstance(payload, dict) else []
    by_id: dict[str, dict[str, object]] = {}
    by_title_index: dict[tuple[str, str], dict[str, object]] = {}
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        factor_id = str(record.get("factor_id") or "")
        if factor_id:
            by_id[factor_id] = record
            factor_index = factor_id.rsplit(":", 1)[-1]
        else:
            factor_index = str(record.get("factor_index") or "")
        title = str(record.get("title") or record.get("article_title") or "")
        if title and factor_index:
            by_title_index[(title, factor_index)] = record
    return by_id, by_title_index


def _row_faithfulness_identity(row: dict[str, object], row_index: int) -> str:
    dedup = str(row.get("dedup_key") or "").strip()
    if dedup:
        return dedup
    url = str(row.get("url") or "").strip()
    if url:
        return "url:" + url
    return f"row:{row_index}:{str(row.get('title') or '')[:80]}"


def _attach_hf_faithfulness_reviews(
    rows: list[dict[str, object]],
    audit_by_id: dict[str, dict[str, object]],
    audit_by_title_index: dict[tuple[str, str], dict[str, object]],
    llm_by_id: dict[str, dict[str, object]],
    llm_by_title_index: dict[tuple[str, str], dict[str, object]],
) -> None:
    if not audit_by_id and not audit_by_title_index and not llm_by_id and not llm_by_title_index:
        return
    for row_index, row in enumerate(rows):
        factors = row.get("paper_hf_factors") or row.get("hf_factor_points") or []
        if not isinstance(factors, list):
            continue
        row_identity = _row_faithfulness_identity(row, row_index)
        title = str(row.get("title") or "")
        for factor_index, factor in enumerate(factors):
            if not isinstance(factor, dict):
                continue
            index_text = str(factor_index)
            factor_id = f"{row_identity}:{index_text}"
            audit = audit_by_id.get(factor_id) or audit_by_title_index.get((title, index_text))
            if audit:
                factor["hf_faithfulness_audit"] = audit
            llm_review = llm_by_id.get(factor_id) or llm_by_title_index.get((title, index_text))
            if llm_review:
                factor["hf_faithfulness_llm_review"] = llm_review


def _publish_hf_faithfulness_reports(reports_dir: Path, public_dir: Path) -> None:
    public_reports_dir = public_dir / "reports"
    public_reports_dir.mkdir(parents=True, exist_ok=True)
    for name in [
        "hf_factor_faithfulness_audit.json",
        "hf_factor_faithfulness_audit.md",
        "hf_factor_faithfulness_audit.html",
        "hf_factor_faithfulness_summary.json",
        "hf_factor_faithfulness_llm_review.json",
    ]:
        source = reports_dir / name
        if source.exists():
            shutil.copy2(source, public_reports_dir / name)
    audit_html = reports_dir / "hf_factor_faithfulness_audit.html"
    if audit_html.exists():
        shutil.copy2(audit_html, public_dir / "hf_factor_faithfulness_audit.html")


def _render_three_ai_faithfulness_audit() -> None:
    if (ROOT / "data" / "latest_three_ai_result.json").exists():
        subprocess.run([sys.executable, "-m", "src.render.three_ai_faithfulness_audit"], cwd=ROOT, check=True)


def _default_paper_hf_proxy_result_dir(data_dir: Path) -> Path:
    current_fields = _manifest_fields(data_dir / "paper_hf_factor_tests_v2" / "manifest.json")
    candidates = [
        path.parent
        for path in [
            *sorted((data_dir / "runtime").glob("render_small_union*/paper_hf_direct_proxy_tests_v2.json")),
            *sorted((data_dir / "guarded_paper_hf_runs").glob("*/results/small1_final_split/paper_hf_direct_proxy_tests_v2.json")),
            *sorted((data_dir / "guarded_paper_hf_runs").glob("*/results/small1/paper_hf_direct_proxy_tests_v2.json")),
            data_dir / "paper_hf_factor_results_small1" / "paper_hf_direct_proxy_tests_v2.json",
            data_dir / "paper_hf_factor_results_v2" / "paper_hf_direct_proxy_tests_v2.json",
        ]
        if path.exists()
    ]
    if not candidates:
        return data_dir / "paper_hf_factor_results_v2"
    if current_fields:
        return max(candidates, key=lambda path: (len(_result_fields(path / "paper_hf_direct_proxy_tests_v2.json") & current_fields), -len(_result_fields(path / "paper_hf_direct_proxy_tests_v2.json") - current_fields), path.stat().st_mtime))
    return max(candidates, key=lambda path: (_result_field_count(path / "paper_hf_direct_proxy_tests_v2.json"), path.stat().st_mtime))


def main() -> None:
    data_dir = ROOT / "data"
    public_dir = ROOT / "public"
    _render_three_ai_faithfulness_audit()
    paper_hf_proxy_result_dir = Path(os.environ.get("PAPER_HF_PROXY_RESULT_DIR", str(_default_paper_hf_proxy_result_dir(data_dir))))
    medium_result_path = Path(os.environ.get("PAPER_HF_MEDIUM_RESULT_PATH", str(data_dir / "paper_hf_factor_results_medium1" / "paper_hf_direct_proxy_tests_v2.json")))
    large_promoted_dir = Path(os.environ.get("PAPER_HF_LARGE_PROMOTED_DIR", str(data_dir / "promoted_factors_large1_selected_final")))
    large_result_dir = Path(os.environ.get("PAPER_HF_LARGE_RESULT_DIR", str(data_dir / "factor_results_large1_selected_final")))
    factor_results = load_factor_results(data_dir / "factor_results")
    paper_hf_proxy_results = load_paper_hf_proxy_results(
        data_dir / "paper_hf_factor_tests_v2",
        paper_hf_proxy_result_dir,
    )
    paper_hf_medium_results = load_paper_hf_medium_results(
        data_dir / "promoted_factors",
        data_dir / "factor_results_medium1",
        medium_result_path,
    )
    paper_hf_large_results = load_paper_hf_large_results(
        large_promoted_dir,
        large_result_dir,
    )
    factor_quality_results = load_factor_quality_results(data_dir / "factor_direction_report.json")
    audit_by_id, audit_by_title_index = _load_hf_faithfulness_records(ROOT / "reports" / "hf_factor_faithfulness_audit.json")
    llm_by_id, llm_by_title_index = _load_hf_faithfulness_llm_reviews(ROOT / "reports" / "hf_factor_faithfulness_llm_review.json")

    rendered_count = 0
    for path in sorted(data_dir.glob("daily_*.jsonl")):
        day = path.stem.replace("daily_", "")
        rows = read_jsonl(path)
        attach_factor_results(rows, factor_results)
        attach_paper_hf_proxy_results(rows, paper_hf_proxy_results)
        attach_paper_hf_medium_results(rows, paper_hf_medium_results)
        attach_paper_hf_large_results(rows, paper_hf_large_results)
        attach_factor_quality_results(rows, factor_quality_results)
        _attach_hf_faithfulness_reviews(rows, audit_by_id, audit_by_title_index, llm_by_id, llm_by_title_index)
        render_daily_page(rows, day, public_dir / f"daily_{day}.html")
        rendered_count += 1

    analysis_archive_path = data_dir / "analysis_archive.jsonl"
    latest_rows = read_jsonl(analysis_archive_path if analysis_archive_path.exists() else data_dir / "latest.jsonl")
    today = datetime.now().strftime("%Y%m%d")
    today_rows = read_jsonl(data_dir / f"daily_{today}.jsonl")
    attach_factor_results(today_rows, factor_results)
    attach_factor_results(latest_rows, factor_results)
    attach_paper_hf_proxy_results(today_rows, paper_hf_proxy_results)
    attach_paper_hf_proxy_results(latest_rows, paper_hf_proxy_results)
    attach_paper_hf_medium_results(today_rows, paper_hf_medium_results)
    attach_paper_hf_medium_results(latest_rows, paper_hf_medium_results)
    attach_paper_hf_large_results(today_rows, paper_hf_large_results)
    attach_paper_hf_large_results(latest_rows, paper_hf_large_results)
    attach_factor_quality_results(today_rows, factor_quality_results)
    attach_factor_quality_results(latest_rows, factor_quality_results)
    _attach_hf_faithfulness_reviews(today_rows, audit_by_id, audit_by_title_index, llm_by_id, llm_by_title_index)
    _attach_hf_faithfulness_reviews(latest_rows, audit_by_id, audit_by_title_index, llm_by_id, llm_by_title_index)
    render_home_page(today_rows, latest_rows, build_history(data_dir), public_dir / "index.html")

    proxy_summary = build_summary(
        data_dir / "paper_hf_factor_tests_v2" / "manifest.json",
        paper_hf_proxy_result_dir / "paper_hf_direct_proxy_tests_v2.json",
        ROOT / "reports" / "paper_hf_medium_candidates.json",
        medium_result_path,
        large_result_dir / "paper_hf_relaxed_medium_candidates.json",
        ROOT / "config" / "proxy_registry.yaml",
        data_dir / "proxy_variable_audit.json",
        analysis_archive_path if analysis_archive_path.exists() else data_dir / "latest.jsonl",
    )
    proxy_block = render_html(proxy_summary)
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "hf_proxy_diversity_summary.json").write_text(
        __import__("json").dumps(proxy_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (reports_dir / "hf_proxy_diversity_summary.html").write_text(proxy_block + "\n", encoding="utf-8")
    _publish_hf_faithfulness_reports(reports_dir, public_dir)
    inject_dashboard(public_dir / "index.html", proxy_block)

    archive_rows = collect_archive_rows(data_dir, [ROOT.parent / "my-paper-digest"])
    attach_factor_results(archive_rows, factor_results)
    attach_paper_hf_proxy_results(archive_rows, paper_hf_proxy_results)
    attach_paper_hf_medium_results(archive_rows, paper_hf_medium_results)
    attach_paper_hf_large_results(archive_rows, paper_hf_large_results)
    attach_factor_quality_results(archive_rows, factor_quality_results)
    _attach_hf_faithfulness_reviews(archive_rows, audit_by_id, audit_by_title_index, llm_by_id, llm_by_title_index)
    render_archive_page(archive_rows, public_dir / "all_factor_archive.html")

    print(f"rendered_daily_pages={rendered_count}")
    print(f"rendered_index={SITE_INDEX_URL}")
    print(f"rendered_archive={public_dir / 'all_factor_archive.html'}")


if __name__ == "__main__":
    main()
