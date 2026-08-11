"""Small dependency-free JSONL persistence helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator


def write_jsonl(path: str | Path, records: Iterable[Any]) -> None:
    """Write records as UTF-8 JSON Lines, creating parent directories."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for record in records:
            value = asdict(record) if is_dataclass(record) else record
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield non-empty JSON objects from a JSONL file."""
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number} is not a JSON object")
            yield value
