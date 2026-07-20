from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def project_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def load_yaml(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"config root must be a mapping: {config_path}")
    return payload


@dataclass(frozen=True)
class ProjectConfig:
    llm: dict[str, Any]
    field_registry: dict[str, Any]
    market_data: dict[str, Any]
    mechanism_taxonomy: dict[str, Any]
    quality_evaluation: dict[str, Any]
    signal_generation: dict[str, Any]


def load_project_config(config_dir: str | Path = "configs") -> ProjectConfig:
    root = Path(config_dir)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    return ProjectConfig(
        llm=load_yaml(root / "llm.yaml"),
        field_registry=load_yaml(root / "field_registry.yaml"),
        market_data=load_yaml(root / "market_data.yaml"),
        mechanism_taxonomy=load_yaml(root / "mechanism_taxonomy.yaml"),
        quality_evaluation=load_yaml(root / "quality_evaluation.yaml"),
        signal_generation=load_yaml(root / "signal_generation.yaml"),
    )