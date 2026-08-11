from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Iterable

import yaml

from agent_alpha.graph_research.ids import sha256_content_hash


@dataclass(frozen=True)
class DataContractV1:
	schema_version: str
	data_contract_id: str
	track: str
	status: str
	sources: tuple[Mapping[str, Any], ...]
	allowed_observables: tuple[str, ...]
	blocked_observables: tuple[str, ...]
	access_policy: Mapping[str, Any]
	contract_hash: str

	@classmethod
	def from_mapping(cls, value: Mapping[str, Any]) -> "DataContractV1":
		payload = dict(value)
		if payload.get("schema_version") != "data_contract_v1":
			raise ValueError("unsupported data contract schema_version")
		for name in ("data_contract_id", "track", "status"):
			if not str(payload.get(name) or "").strip():
				raise ValueError(f"data contract requires {name}")
		sources = tuple(payload.get("sources") or ())
		if not sources:
			raise ValueError("data contract requires at least one source")
		allowed = tuple(str(item) for item in payload.get("allowed_observables") or ())
		blocked = tuple(str(item) for item in payload.get("blocked_observables") or ())
		if set(allowed) & set(blocked):
			raise ValueError("allowed and blocked observables must be disjoint")
		identity = {key: item for key, item in payload.items() if key != "contract_hash"}
		contract_hash = sha256_content_hash(identity)
		declared_hash = str(payload.get("contract_hash") or "")
		if declared_hash and declared_hash != contract_hash:
			raise ValueError("declared data contract hash does not match content")
		return cls(
			schema_version="data_contract_v1",
			data_contract_id=str(payload["data_contract_id"]),
			track=str(payload["track"]),
			status=str(payload["status"]),
			sources=sources,
			allowed_observables=allowed,
			blocked_observables=blocked,
			access_policy=dict(payload.get("access_policy") or {}),
			contract_hash=contract_hash,
		)

	@classmethod
	def load(cls, path: str | Path) -> "DataContractV1":
		payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
		if not isinstance(payload, Mapping):
			raise ValueError("data contract YAML must contain an object")
		return cls.from_mapping(payload)

	def validate_observables(self, required: Iterable[str]) -> None:
		requested = {str(item) for item in required}
		blocked = requested & set(self.blocked_observables)
		unknown = requested - set(self.allowed_observables)
		if blocked:
			raise ValueError("blocked observables requested: " + ",".join(sorted(blocked)))
		if unknown:
			raise ValueError("observables outside data contract: " + ",".join(sorted(unknown)))

	def validate_access(self, path: str | Path) -> Path:
		resolved = Path(path).resolve()
		exact_paths = {Path(item).resolve() for item in self.access_policy.get("exact_paths", [])}
		allowed_roots = tuple(Path(item).resolve() for item in self.access_policy.get("allowed_roots", []))
		if resolved in exact_paths:
			return resolved
		if any(resolved == root or root in resolved.parents for root in allowed_roots):
			return resolved
		raise PermissionError(f"path is outside data contract allowlist: {resolved}")

	def verify_sources(self, *, require_snapshot_manifest: bool = True) -> None:
		if require_snapshot_manifest and self.access_policy.get("snapshot_manifest_required"):
			manifest = self.access_policy.get("snapshot_manifest")
			if not manifest or not Path(str(manifest)).exists():
				raise ValueError("data contract requires a frozen snapshot manifest")
		for source in self.sources:
			path = self.validate_access(str(source.get("path") or ""))
			if not path.exists():
				raise FileNotFoundError(path)
			expected = str(source.get("content_sha256") or "")
			if expected and path.is_file():
				digest = hashlib.sha256()
				with path.open("rb") as handle:
					for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
						digest.update(chunk)
				if digest.hexdigest() != expected.removeprefix("sha256:"):
					raise ValueError(f"data source content hash mismatch: {path}")


class DataContractRegistry:
	def __init__(self, contracts: Iterable[DataContractV1]) -> None:
		items = tuple(contracts)
		self._contracts = {item.data_contract_id: item for item in items}
		if len(self._contracts) != len(items):
			raise ValueError("duplicate data contract IDs")

	@classmethod
	def load_directory(cls, directory: str | Path) -> "DataContractRegistry":
		return cls(DataContractV1.load(path) for path in sorted(Path(directory).glob("*.yaml")))

	def get(self, data_contract_id: str) -> DataContractV1:
		try:
			return self._contracts[data_contract_id]
		except KeyError:
			raise KeyError(f"unknown data contract: {data_contract_id}") from None


__all__ = ["DataContractRegistry", "DataContractV1"]
