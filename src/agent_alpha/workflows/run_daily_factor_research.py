from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

from agent_alpha.daily_research.evaluator import (
	evaluate_daily_factor_detailed,
	sanitize_daily_returns,
)
from agent_alpha.daily_research.experiment import DailyExperimentSpecV1
from agent_alpha.daily_research.features import compute_return_only_feature
from agent_alpha.daily_research.store import DailyReturnStore
from agent_alpha.data_interfaces.data_contracts import DataContractV1
from agent_alpha.graph_research.ids import sha256_content_hash


def atomic_write_json(path: Path, value: object) -> None:
	temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
	temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
	os.replace(temporary, path)


def main() -> int:
	parser = argparse.ArgumentParser(description="Run one preregistered return-only daily factor experiment.")
	parser.add_argument("--experiment", type=Path, required=True)
	parser.add_argument("--data-contract", type=Path, required=True)
	parser.add_argument("--output-dir", type=Path, required=True)
	parser.add_argument("--allow-locked-test", action="store_true")
	parser.add_argument("--skip-source-hash-check", action="store_true")
	parser.add_argument("--replace", action="store_true")
	args = parser.parse_args()
	payload = yaml.safe_load(args.experiment.read_text(encoding="utf-8"))
	if not isinstance(payload, dict):
		raise ValueError("daily experiment YAML must contain an object")
	spec = DailyExperimentSpecV1.from_mapping(payload)
	if spec.stage == "locked_test" and not args.allow_locked_test:
		raise SystemExit("locked_test requires explicit --allow-locked-test")
	contract = DataContractV1.load(args.data_contract)
	if spec.data_contract_id != contract.data_contract_id or spec.data_contract_hash != contract.contract_hash:
		raise ValueError("daily experiment data contract identity mismatch")
	known = ("manifest.json", "preregistration.json", "aggregate.json", "daily_metrics.parquet")
	if args.output_dir.exists() and not args.replace and any((args.output_dir / name).exists() for name in known):
		raise SystemExit(f"daily experiment output exists; use --replace: {args.output_dir}")
	args.output_dir.mkdir(parents=True, exist_ok=True)
	returns = DailyReturnStore(contract).load(verify_content_hash=not args.skip_source_hash_check)
	clean = sanitize_daily_returns(returns, max_abs_return=spec.max_abs_return)
	feature = compute_return_only_feature(
		clean, operator=spec.operator, window=spec.window, min_periods=spec.min_periods
	)
	aggregate, daily = evaluate_daily_factor_detailed(
		feature,
		clean,
		factor_id=spec.factor_id,
		stage=spec.stage,
		date_start=spec.date_start,
		date_end=spec.date_end,
		horizon=spec.horizon,
		direction=spec.direction,
		min_cross_sectional_obs=spec.min_cross_sectional_obs,
		max_abs_return=spec.max_abs_return,
	)
	atomic_write_json(args.output_dir / "preregistration.json", spec.to_dict())
	atomic_write_json(args.output_dir / "aggregate.json", aggregate.to_dict())
	daily_path = args.output_dir / "daily_metrics.parquet"
	temporary_daily = daily_path.with_name(f".{daily_path.name}.tmp-{os.getpid()}")
	daily.to_parquet(temporary_daily)
	os.replace(temporary_daily, daily_path)
	manifest = {
		"schema_version": "daily_experiment_manifest_v1",
		"daily_experiment_id": spec.daily_experiment_id,
		"stage": spec.stage,
		"data_contract_id": contract.data_contract_id,
		"data_contract_hash": contract.contract_hash,
		"source_content_hash": contract.sources[0].get("content_sha256"),
		"preregistration_hash": sha256_content_hash(spec.to_dict()),
		"aggregate_hash": sha256_content_hash(aggregate.to_dict()),
		"daily_metrics_path": str(daily_path),
		"daily_metrics_row_count": len(daily),
		"locked_test_authorized": bool(args.allow_locked_test),
	}
	atomic_write_json(args.output_dir / "manifest.json", manifest)
	print(json.dumps({
		"output_dir": str(args.output_dir),
		"daily_experiment_id": spec.daily_experiment_id,
		"stage": spec.stage,
		"n_dates": aggregate.n_dates,
		"daily_rankic_mean": aggregate.daily_rankic_mean,
	}, ensure_ascii=False))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
