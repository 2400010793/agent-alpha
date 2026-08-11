import json

import pytest

from paper_graph.taxonomy import load_extension, merge_taxonomy, validate_taxonomy


BASE = (
    {"id": "base_a", "label": "A", "children": {"child_a": ("A1", "alpha")}},
    {"id": "base_b", "label": "B", "children": {"child_b": ("B1", "beta")}},
)


def test_additive_extension_preserves_existing_ids(tmp_path) -> None:
    path = tmp_path / "extension.json"
    path.write_text(json.dumps({
        "schema_version": "quant_research_taxonomy_extension_v1",
        "taxonomy_version": "candidate-v2",
        "status": "candidate",
        "mode": "additive_only",
        "base_first_level_count": 2,
        "base_second_level_count": 2,
        "add_first_levels": [
            {"id": "new_parent", "label": "New", "children": {"new_child": ["New child", "term"]}}
        ],
    }), encoding="utf-8")
    merged, summary = merge_taxonomy(BASE, load_extension(path))
    assert [parent["id"] for parent in merged] == ["base_a", "base_b", "new_parent"]
    assert summary.taxonomy_version == "candidate-v2"
    assert summary.first_level_count == 3
    assert summary.second_level_count == 3


def test_extension_rejects_duplicate_child_ids() -> None:
    with pytest.raises(ValueError, match="duplicate taxonomy child id"):
        validate_taxonomy((
            {"id": "a", "label": "A", "children": {"same": ("one",)}},
            {"id": "b", "label": "B", "children": {"same": ("two",)}},
        ))


def test_extension_refuses_wrong_base_shape() -> None:
    with pytest.raises(ValueError, match="base_first_level_count"):
        merge_taxonomy(BASE, {
            "taxonomy_version": "bad-v2",
            "base_first_level_count": 12,
            "add_first_levels": [],
        })
