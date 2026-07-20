from __future__ import annotations

from agent_alpha.agents.prompt_registry import load_prompt_registry, prompt_paths_for_tags
from agent_alpha.taxonomy.hf_taxonomy import load_hf_mechanisms


def test_all_hf_mechanisms_have_existing_prompt_files() -> None:
    mechanisms = load_hf_mechanisms()
    registry = load_prompt_registry()
    assert mechanisms
    assert set(registry) == {item["id"] for item in mechanisms}
    for spec in registry.values():
        assert spec.path.exists()
        text = spec.read_text()
        assert "High-Frequency" in text or "high-frequency" in text
        assert "forecast" in text


def test_prompt_paths_for_tags() -> None:
    paths = prompt_paths_for_tags(["order_book_pressure", "spread_liquidity", "missing"])
    assert len(paths) == 2
    assert paths[0].name == "agent_order_book_pressure.md"