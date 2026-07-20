from __future__ import annotations

from agent_alpha.config import load_project_config
from agent_alpha.workflows.generate_signals_from_papers import main


def test_load_project_config() -> None:
    config = load_project_config()
    assert config.field_registry["schema_version"] == "hf_field_registry_v2"
    assert "askP1" in config.field_registry["allowed_input_fields"]
    assert "mid_price_l1" in config.field_registry["derived_feature_fields"]


def test_generate_signals_dry_run(capsys) -> None:
    rc = main(["--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "The Idea Person" in out
    assert "paper crawling is skipped" in out