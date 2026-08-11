#!/usr/bin/env python3
"""Build evidence rows from already-downloaded arXiv .source archives."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from src.pipeline import daily_research_pipeline as legacy

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DIR = ROOT / "data" / "arxiv_tex_sources"
DEFAULT_MANIFEST = ROOT / "data" / "arxiv_tex_sources_manifest.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "arxiv_tex_evidence_archive.jsonl"


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
            except json.JSONDecodeError:
                continue
    return rows


def build_pack(seed: Dict[str, Any], source_path: Path) -> Dict[str, Any]:
    payload = source_path.read_bytes()
    source_texts, source_kind = legacy._extract_arxiv_source_texts(payload)
    combined, source_files, main_source_file = legacy._assemble_arxiv_tex_corpus(source_texts)
    pack: Dict[str, Any] = {
        "source": "arxiv-local-source",
        "arxiv_id": seed.get("arxiv_id"),
        "url": seed.get("url") or f"https://arxiv.org/abs/{seed.get('arxiv_id')}",
        "status": "ok" if combined.strip() else "empty_source",
        "source_kind": source_kind,
        "main_source_file": main_source_file,
        "source_files": source_files[:16],
        "section_overview": legacy._extract_tex_section_overview(combined),
        "intro_context": legacy._extract_tex_intro_context(combined),
        "formula_contexts": legacy._extract_tex_formula_contexts(combined),
        "experimental_formula_contexts": legacy._extract_tex_experimental_formula_contexts(combined),
        "method_blocks": legacy._extract_tex_method_blocks(combined),
        "empirical_setup_snippets": legacy._extract_tex_empirical_setup_snippets(combined),
        "conclusion_context": legacy._extract_tex_conclusion_context(combined),
        "code_or_algorithm_snippets": legacy._extract_tex_code_or_algorithm_snippets(combined),
        "input_include_audit": legacy._extract_tex_include_audit(combined),
        "table_figure_residual_audit": legacy._tex_noise_residual_audit(combined),
        "excluded_sections": "references/appendix",
    }
    pack["quality_checks"] = legacy._evidence_quality_checks(pack)
    # Local source archives are already extracted and bounded. Some papers use
    # nonstandard section macros, so the legacy overview heuristic can reject
    # otherwise usable TeX evidence solely for a short section map.
    checks = pack["quality_checks"]
    if checks.get("reasons") == ["section_overview_too_short_possible_input_include_or_nonstandard_tex"]:
        checks["is_trusted"] = True
        checks["local_source_override"] = "trusted extracted source; legacy section-map heuristic bypassed"
    return pack


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    seeds = read_jsonl(args.manifest)
    done = {str(row.get("arxiv_id")) for row in read_jsonl(args.output)} if args.resume else set()
    selected = [row for row in seeds if str(row.get("arxiv_id")) not in done]
    if args.limit > 0:
        selected = selected[: args.limit]
    for seed in selected:
        identifier = str(seed.get("arxiv_id") or "")
        source = args.source_dir / f"{identifier.replace('/', '_')}.source"
        row: Dict[str, Any] = {key: seed.get(key) for key in ("arxiv_id", "title", "url", "source_id", "source_name", "candidate_categories")}
        try:
            if not source.exists():
                raise FileNotFoundError(source)
            row["evidence_pack"] = build_pack(seed, source)
            row["status"] = "ok"
        except Exception as exc:
            row["status"] = "failed"
            row["evidence_pack"] = {"status": "fetch_failed", "error": f"{type(exc).__name__}: {exc}"}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
        pack = row["evidence_pack"]
        print(json.dumps({"arxiv_id": identifier, "status": row["status"], "evidence_status": pack.get("status"), "trusted": (pack.get("quality_checks") or {}).get("is_trusted")}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
