from __future__ import annotations

from agent_alpha.taxonomy.taxonomy_mapper import map_hf_tags_to_roles


def select_runtime_agents(hf_mechanism_tags: list[str]) -> list[str]:
    """Select runtime roles from HF mechanism tags."""
    roles = map_hf_tags_to_roles(hf_mechanism_tags)
    return roles or ["AgentComposite"]