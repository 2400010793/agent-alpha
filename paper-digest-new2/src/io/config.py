"""Source configuration loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml


@dataclass
class SourceConfig:
	source_id: str
	feed_type: str
	source_type: str
	source_name: str
	url: str
	enabled: bool
	max_items: Optional[int] = None
	max_age_days: Optional[int] = None
	use_proxy: bool = True
	local_file: str = ""


def load_config(config_path: Path) -> Tuple[Dict[str, object], List[SourceConfig]]:
	payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
	if not isinstance(payload, dict):
		raise ValueError("config yaml must be an object")
	defaults = payload.get("defaults", {})
	if not isinstance(defaults, dict):
		raise ValueError("defaults must be an object")
	src_list = payload.get("sources", [])
	if not isinstance(src_list, list):
		raise ValueError("sources must be a list")
	sources: List[SourceConfig] = []
	for raw in src_list:
		if not isinstance(raw, dict):
			continue
		sources.append(
			SourceConfig(
				source_id=str(raw.get("id", "")),
				feed_type=str(raw.get("type", "rss")),
				source_type=str(raw.get("source_type", "paper")),
				source_name=str(raw.get("source_name", raw.get("id", ""))),
				url=str(raw.get("url", "")),
				enabled=bool(raw.get("enabled", True)),
				max_items=int(raw["max_items"]) if str(raw.get("max_items", "")).strip() else None,
				max_age_days=int(raw["max_age_days"]) if str(raw.get("max_age_days", "")).strip() else None,
				use_proxy=bool(raw.get("use_proxy", True)),
				local_file=str(raw.get("local_file", "")),
			)
		)
	return defaults, sources


__all__ = ["SourceConfig", "load_config"]