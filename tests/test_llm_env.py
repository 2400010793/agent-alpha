from __future__ import annotations

import pytest

from agent_alpha.llm.client import settings_from_env


def test_settings_from_env_uses_agent_alpha_prefix(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_ALPHA_LLM_API_KEY", "secret-value")
    monkeypatch.setenv("AGENT_ALPHA_LLM_MODEL", "openai/gpt-4o-mini")
    settings = settings_from_env(
        {
            "base_url_env": "AGENT_ALPHA_LLM_BASE_URL",
            "api_key_envs": ["AGENT_ALPHA_LLM_API_KEY"],
            "model_env": "AGENT_ALPHA_LLM_MODEL",
            "default_base_url": "https://models.github.ai/inference",
            "default_timeout_sec": 300,
            "default_retries": 2,
            "default_min_interval_sec": 10,
        }
    )
    assert settings.api_key == "secret-value"
    assert settings.model == "openai/gpt-4o-mini"


def test_settings_from_env_requires_key() -> None:
    with pytest.raises(RuntimeError):
        settings_from_env({"api_key_envs": ["MISSING_KEY"]})