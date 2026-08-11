from __future__ import annotations

from pathlib import Path

import pandas as pd

from agent_alpha.data_interfaces.data_contracts import DataContractV1


class DailyReturnStore:
	"""Read the single authorized wide daily-return store."""

	def __init__(self, contract: DataContractV1) -> None:
		if contract.track != "daily_cross_sectional":
			raise ValueError("DailyReturnStore requires a daily_cross_sectional contract")
		contract.validate_observables(["RETURN_HISTORY"])
		if len(contract.sources) != 1:
			raise ValueError("daily return contract must define exactly one source")
		self.contract = contract
		self.path = contract.validate_access(str(contract.sources[0].get("path") or ""))

	def load(self, *, verify_content_hash: bool = True) -> pd.DataFrame:
		if verify_content_hash:
			self.contract.verify_sources(require_snapshot_manifest=False)
		frame = pd.read_parquet(self.path)
		if not isinstance(frame, pd.DataFrame) or frame.empty:
			raise ValueError("daily return store must be a non-empty DataFrame")
		frame = frame.copy()
		frame.index = pd.to_datetime(frame.index)
		if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
			raise ValueError("daily return index must be unique and increasing")
		if frame.columns.has_duplicates:
			raise ValueError("daily return ticker columns must be unique")
		return frame.apply(pd.to_numeric, errors="coerce").astype(float)


__all__ = ["DailyReturnStore"]
