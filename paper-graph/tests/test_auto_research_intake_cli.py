import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_offline_intake_cli_builds_ready_agent_alpha_package(tmp_path) -> None:
    graph = {
        "schema_version": "fixture_graph_v1",
        "graph_id": "graph:daily-momentum",
        "topic_id": "short_term_momentum",
        "seed_ids": ["paper:momentum"],
        "nodes": [{"id": "paper:momentum", "is_seed": True}],
        "edges": [],
    }
    features = {
        "schema_version": "graph_value_features_v1",
        "graph_id": "graph:daily-momentum",
        "topic_ids": ["short_term_momentum"],
        "target_track": "daily_cross_sectional",
        "data_contract_id": "daily_ret_wide_v1",
        "evidence_readiness": 0.9,
        "data_feasibility": 1.0,
        "direct_observability": 1.0,
        "graph_coherence": 0.8,
        "novelty": 0.6,
        "claim_relation_coverage": 0.3,
        "contradiction_density": 0.0,
        "downstream_utility": 0.9,
        "redundancy": 0.1,
        "estimated_cost": 0.2,
        "evidence_gap_count": 0
    }
    artifact = {
        "schema_version": "structured_paper_artifact_ref_v1",
        "artifact_id": "artifact:momentum",
        "paper_id": "paper:momentum",
        "document_version": "v1",
        "content_hash": "sha256:paper",
        "claim_ids": ["claim:momentum"],
        "evidence_ids": ["evidence:momentum"],
        "contribution_types": ["EMPIRICAL_EFFECT"]
    }
    graph_path = tmp_path / "graph.json"
    feature_path = tmp_path / "features.json"
    artifact_path = tmp_path / "artifacts.jsonl"
    budget_path = tmp_path / "budget.json"
    output = tmp_path / "output"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    feature_path.write_text(json.dumps(features), encoding="utf-8")
    artifact_path.write_text(json.dumps(artifact) + "\n", encoding="utf-8")
    budget_path.write_text(json.dumps({"max_hypotheses": 2}), encoding="utf-8")
    result = subprocess.run([
        sys.executable,
        str(ROOT / "scripts" / "build_auto_research_intake.py"),
        "--graph", str(graph_path),
        "--graph-features", str(feature_path),
        "--structured-artifacts", str(artifact_path),
        "--output-dir", str(output),
        "--as-of-date", "2026-08-11",
        "--taxonomy-version", "quant_research_topics_v2_candidate",
        "--research-question", "Does return-only momentum predict future cross-sectional returns?",
        "--required-observable", "RETURN_HISTORY",
        "--producer-revision", "fixture-rev",
        "--config-hash", "fixture-config",
        "--data-contract-id", "daily_ret_wide_v1",
        "--data-contract-hash", "sha256:daily",
        "--field-registry-version", "daily-fields-v1",
        "--operator-registry-version", "daily-ops-v1",
        "--memory-snapshot-id", "memory:empty",
        "--research-budget-file", str(budget_path),
    ], cwd=ROOT, check=True, capture_output=True, text=True)
    summary = json.loads(result.stdout)
    assert summary["status"] == "READY"
    assert summary["package_id"].startswith("researchpkg:")
    package = json.loads((output / "factor_research_package.json").read_text())
    assert package["target_track"] == "daily_cross_sectional"
    assert package["data_contract_id"] == "daily_ret_wide_v1"
