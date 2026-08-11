#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET = ROOT / "data" / "hf_factor_faithfulness_reviews.json"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"expected JSON object in {path}")
    return data


def normalize_reviews(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_reviews = payload.get("reviews", payload)
    if not isinstance(raw_reviews, dict):
        raise SystemExit("expected a reviews object")
    reviews: dict[str, dict[str, Any]] = {}
    for factor_id, review in raw_reviews.items():
        if not isinstance(review, dict):
            continue
        verdict = str(review.get("verdict") or "").strip()
        if not verdict:
            continue
        reviews[str(factor_id)] = {
            "verdict": verdict,
            "reviewer": str(review.get("reviewer") or "human"),
            "score": str(review.get("score") or verdict),
            "notes": str(review.get("notes") or ""),
            "reviewed_at": str(review.get("reviewed_at") or datetime.now(timezone.utc).isoformat()),
        }
    return reviews


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge exported HF faithfulness human review JSON into new2 data.")
    parser.add_argument("review_json", help="JSON exported from the HF faithfulness audit page")
    parser.add_argument("--target", default=str(DEFAULT_TARGET))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = Path(args.review_json).expanduser().resolve()
    target = Path(args.target).expanduser().resolve()
    incoming = normalize_reviews(load_json(source))
    existing_payload = load_json(target) if target.exists() else {"version": 1, "reviews": {}}
    existing_reviews = existing_payload.get("reviews") if isinstance(existing_payload.get("reviews"), dict) else {}
    merged = {str(key): value for key, value in existing_reviews.items() if isinstance(value, dict)}
    merged.update(incoming)
    output = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "reviews": merged,
    }
    if not args.dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "dry_run" if args.dry_run else "ok", "target": str(target), "incoming": len(incoming), "total": len(merged)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())