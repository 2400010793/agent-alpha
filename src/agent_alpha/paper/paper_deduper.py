from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.casefold()).strip()


def dedupe_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = str(record.get("doi") or record.get("arxiv_id") or record.get("source_url") or "").strip().casefold()
        if not key:
            key = normalize_title(str(record.get("title", "")))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped