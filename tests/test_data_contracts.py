from pathlib import Path

import pytest

from agent_alpha.data_interfaces.data_contracts import DataContractRegistry, DataContractV1


ROOT = Path(__file__).resolve().parents[1]


def test_daily_contract_allows_only_the_frozen_return_store() -> None:
	contract = DataContractV1.load(ROOT / "configs/data_contracts/daily_ret_wide_v1.yaml")
	assert contract.track == "daily_cross_sectional"
	contract.validate_observables(["RETURN_HISTORY"])
	with pytest.raises(ValueError, match="blocked observables"):
		contract.validate_observables(["VOLUME_TURNOVER"])
	assert contract.validate_access("/home/gaozh/ret.parquet") == Path("/home/gaozh/ret.parquet").resolve()
	with pytest.raises(PermissionError):
		contract.validate_access("/home/gaozh/other_daily.parquet")


def test_intraday_contract_fails_closed_without_snapshot_manifest() -> None:
	contract = DataContractV1.load(ROOT / "configs/data_contracts/intraday_hf_v1.yaml")
	with pytest.raises(ValueError, match="frozen snapshot manifest"):
		contract.verify_sources()


def test_registry_loads_both_tracks() -> None:
	registry = DataContractRegistry.load_directory(ROOT / "configs/data_contracts")
	assert registry.get("daily_ret_wide_v1").track == "daily_cross_sectional"
	assert registry.get("intraday_hf_v1").track == "intraday_hf"
