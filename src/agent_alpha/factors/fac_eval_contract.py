from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_alpha.config import load_yaml


@dataclass(frozen=True)
class FacEvalDataConfig:
    trade_data_dir: Path
    time_column: str
    default_horizons: tuple[str, ...]

    @classmethod
    def from_yaml(cls, path: str | Path = "configs/market_data.yaml") -> "FacEvalDataConfig":
        payload = load_yaml(path)
        return cls(
            trade_data_dir=Path(str(payload.get("trade_data_dir", "data/market_data"))).expanduser(),
            time_column=str(payload.get("time_column", "delay_time")),
            default_horizons=tuple(str(x) for x in payload.get("default_horizons", ["ret60s"])),
        )


class FacEvalContract:
    def __init__(self, config: FacEvalDataConfig) -> None:
        self.config = config

    def trade_path(self, date: str, code: str) -> Path:
        stock = str(code).strip().upper()
        if stock.startswith(("SH", "SZ")) and stock[2:].isdigit():
            stock = stock[2:].zfill(6)
        elif stock.isdigit():
            stock = stock.zfill(6)
        return self.config.trade_data_dir / str(date) / f"{stock}.parquet"

    def describe_contract(self) -> dict[str, Any]:
        return {
            "trade_data_dir": str(self.config.trade_data_dir),
            "time_column": self.config.time_column,
            "default_horizons": list(self.config.default_horizons),
            "factor_contract": "fields + compute_factor(code, date, df) -> pandas.DataFrame",
        }