from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _coerce_scalar(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text == "":
        return None
    lowered = text.casefold()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if any(marker in text for marker in (".", "e", "E")):
            return float(text)
        return int(text)
    except ValueError:
        return value


def _coerce_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _coerce_scalar(value) for key, value in row.items()}


def _coerce_rows(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        if isinstance(payload.get("rows"), list):
            return [_coerce_row(row) for row in payload["rows"] if isinstance(row, dict)]
        if isinstance(payload.get("metrics"), dict):
            return [_coerce_row(payload["metrics"])]
        return [_coerce_row(payload)]
    if isinstance(payload, list):
        return [_coerce_row(row) for row in payload if isinstance(row, dict)]
    raise ValueError("fac-eval metrics JSON must be an object or list of objects")


def read_stock_level_metrics(path: str | Path) -> list[dict]:
    metrics_path = Path(path)
    suffix = metrics_path.suffix.lower()
    if suffix == ".json":
        return _coerce_rows(json.loads(metrics_path.read_text(encoding="utf-8")))
    if suffix == ".csv":
        with metrics_path.open("r", encoding="utf-8", newline="") as handle:
            return [_coerce_row(dict(row)) for row in csv.DictReader(handle)]
    if suffix == ".parquet":
        try:
            import pandas as pd  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError("reading parquet fac-eval metrics requires pandas/pyarrow") from exc
        return [_coerce_row(row) for row in pd.read_parquet(metrics_path).to_dict(orient="records")]
    raise ValueError(f"unsupported fac-eval metrics file: {metrics_path}")


def read_fac_eval_metrics(path: str | Path) -> list[dict]:
    return read_stock_level_metrics(path)


__all__ = ["read_fac_eval_metrics", "read_stock_level_metrics"]