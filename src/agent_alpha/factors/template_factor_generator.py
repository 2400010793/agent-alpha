from __future__ import annotations

import hashlib
import re
from typing import Any

from agent_alpha.config import load_yaml
from agent_alpha.factors.factor_schema import FactorCandidate
from agent_alpha.factors.field_guard import extract_expression_tokens
from agent_alpha.rag.field_registry import FieldRegistry
from agent_alpha.taxonomy.taxonomy_mapper import map_hf_tags_to_roles


def _safe_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    return text[:80] or "factor"


def _hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def generate_template_factor_candidates(signal: dict[str, Any], config_path: str = "configs/factor_mining.yaml") -> list[dict[str, Any]]:
    """Temporary non-LLM baseline generator for smoke tests only."""
    config = load_yaml(config_path)
    registry = FieldRegistry.from_yaml()
    templates = dict(config.get("default_expression_templates", {}))
    tags = [str(tag) for tag in signal.get("hf_mechanism_tags", [])] or ["price_volume_divergence"]
    candidates: list[dict[str, Any]] = []
    for tag in tags:
        expression = str(templates.get(tag) or templates.get("price_volume_divergence") or "zscore(volume)")
        signal_id = str(signal.get("signal_id") or "signal")
        factor_name = f"{config.get('default_factor_prefix', 'alpha_hf')}_{_safe_id(tag)}_{_hash(signal_id + expression)}"
        expression_fields = [token for token in extract_expression_tokens(expression) if registry.is_allowed_input(token)]
        candidate = FactorCandidate(
            factor_id=factor_name,
            name=factor_name,
            expression=expression,
            fields=expression_fields,
            windows=[],
            direction=str(signal.get("expected_direction") or "unknown"),
            source_signal_id=signal_id,
            source_reading_note_id=str(signal.get("source_reading_note_id") or signal.get("source_paper_id") or ""),
            mechanism_tags=[tag],
        )
        payload = candidate.to_dict()
        payload["cogalpha_roles"] = map_hf_tags_to_roles([tag])
        payload["economic_rationale"] = str(signal.get("market_intuition") or signal.get("hypothesis") or "")
        candidates.append(payload)
    return candidates