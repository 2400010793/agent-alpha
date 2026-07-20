from __future__ import annotations

import json
from pathlib import Path


def write_backtest_report(path: str | Path, report: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")