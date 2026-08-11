from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.pipeline import archive_filters


ROOT = Path(__file__).resolve().parents[2]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
    return rows


def _identity(row: dict[str, Any]) -> str:
    dedup_key = str(row.get("dedup_key") or "").strip()
    if dedup_key:
        return f"dedup:{dedup_key}"
    url = str(row.get("url") or "").strip().lower()
    if url:
        return f"url:{url}"
    title = " ".join(str(row.get("title") or "").lower().split())
    source = str(row.get("source_id") or "").lower().strip()
    return f"title:{source}:{title}"


def _row_score(row: dict[str, Any]) -> tuple[int, int, int, str]:
    agent = str(row.get("analysis_agent") or "")
    factors = row.get("paper_hf_factors") or row.get("hf_factor_points") or []
    factor_count = len(factors) if isinstance(factors, list) else 0
    return (
        2 if "schema-v6" in agent else 0,
        1 if str(row.get("analysis_version") or "") == "v2" else 0,
        factor_count,
        str(row.get("fetched_at") or row.get("publish_time") or ""),
    )


def _has_real_hf_formula(row: dict[str, Any]) -> bool:
    factors = row.get("paper_hf_factors") or row.get("hf_factor_points") or []
    if not isinstance(factors, list):
        return False
    for factor in factors:
        if not isinstance(factor, dict):
            continue
        formula = str(factor.get("mechanism_formula") or factor.get("formula") or "").strip()
        if formula and "待 LLM" not in formula and "待LLM" not in formula and not factor.get("is_placeholder"):
            return True
    return False


def _keep_for_analysis_archive(row: dict[str, Any]) -> bool:
    agent = str(row.get("analysis_agent") or "")
    if "schema-v6" in agent or str(row.get("analysis_version") or "") == "v2":
        return True
    if not archive_filters.is_display_quality_row(row):
        return False
    score = archive_filters._metric_float(row.get("recommendation_score")) or 0.0
    if score < 5.0:
        return False
    if "schema-v6" in agent:
        return True
    if agent.startswith("paper-llm-agent:") and _has_real_hf_formula(row):
        return True
    return True


def build_archive_input(data_dir: Path, hf_only: bool = False) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for path in [data_dir / "analysis_archive.jsonl", data_dir / "latest.jsonl", *sorted(data_dir.glob("daily_*.jsonl"))]:
        for row in _read_jsonl(path):
            key = _identity(row)
            previous = by_key.get(key)
            if previous is None or _row_score(row) > _row_score(previous):
                by_key[key] = row
    rows = [row for row in by_key.values() if _keep_for_analysis_archive(row)]
    if hf_only:
        rows = [row for row in rows if row.get("paper_hf_factors") or row.get("hf_factor_points")]
    return sorted(rows, key=lambda row: str(row.get("publish_time") or ""), reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the cumulative analysis archive used by LLM dashboards and HF variant generation.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / "data/analysis_archive.jsonl")
    parser.add_argument("--hf-only", action="store_true", help="Write only rows with paper HF factors.")
    args = parser.parse_args()

    rows = build_archive_input(args.data_dir, hf_only=bool(args.hf_only))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"status": "ok", "rows": len(rows), "output": str(args.output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())