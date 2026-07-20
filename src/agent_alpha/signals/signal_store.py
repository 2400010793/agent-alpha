from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_alpha.signals.signal_schema import validate_alpha_signal


def write_signals(path: str | Path, signals: list[dict]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(signals, ensure_ascii=False, indent=2), encoding="utf-8")


def write_signals_json(path: str | Path, signals: list[dict[str, Any]]) -> Path:
    for signal in signals:
        validate_alpha_signal(signal)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"signals": signals}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def append_signals_jsonl(path: str | Path, signals: list[dict[str, Any]]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as handle:
        for signal in signals:
            validate_alpha_signal(signal)
            handle.write(json.dumps(signal, ensure_ascii=False, sort_keys=True) + "\n")
    return out


def load_signals_json(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    signals = payload.get("signals", payload) if isinstance(payload, dict) else payload
    if not isinstance(signals, list):
        raise ValueError("signal JSON must be a list or an object with key 'signals'")
    for signal in signals:
        validate_alpha_signal(signal)
    return signals


def load_signals_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    signal_path = Path(path)
    if not signal_path.exists():
        return records
    with signal_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError(f"signal JSONL record must be an object at line {line_number}")
            validate_alpha_signal(payload)
            records.append(payload)
    return records