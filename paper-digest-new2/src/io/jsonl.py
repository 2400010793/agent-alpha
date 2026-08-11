"""JSONL read/write helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


def read_jsonl(path: Path) -> List[Dict[str, object]]:
	if not path.exists():
		return []
	rows: List[Dict[str, object]] = []
	with path.open("r", encoding="utf-8") as handle:
		for line in handle:
			line = line.strip()
			if not line:
				continue
			rows.append(json.loads(line))
	return rows


def write_jsonl(path: Path, rows: List[Dict[str, object]]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8") as handle:
		for row in rows:
			handle.write(json.dumps(row, ensure_ascii=False) + "\n")


__all__ = ["read_jsonl", "write_jsonl"]