#!/usr/bin/env python3
"""No-network, fake-LLM contract test for one approved Digest seed."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DIGEST_ROOT = Path("/home/gaozh/my-paper-digest-new2")
ALPHA_ROOT = Path("/home/gaozh/agent_alpha")
sys.path.insert(0, str(DIGEST_ROOT))
sys.path.insert(0, str(ALPHA_ROOT / "src"))

from src.llm.three_ai.research_artifact_exporter import export_research_artifact_envelope  # noqa: E402
from agent_alpha.adapters.research_artifact import reading_note_from_envelope  # noqa: E402
from paper_graph.research_contracts import ResearchArtifactEnvelopeV1, ResearchFeedbackV1  # noqa: E402


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-manifest", type=Path, default=ROOT / "data/processed/openalex_seed_manifests_v1/digest_seed_manifest.jsonl")
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs/three_project_contract_v1")
    args = parser.parse_args()
    seeds = [json.loads(line) for line in args.seed_manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    seed = next(row for row in seeds if row["selection_status"] == "approved")

    # Fake LLM output: evidence-bound and deterministic, with no network call.
    evidence = [{"evidence_id": "ev:momentum:001", "chunk_id": "chunk:method:001", "text": "The changepoint module improves responsiveness to regime change."}]
    note = {"schema_version": "reading_note_v1", "reading_note_id": "note:slow-momentum-v1", "title": seed["title"], "recommendation_score": 8.0, "mechanism_chain": ["detect regime change", "switch momentum/reversion exposure"], "evidence_ids": [evidence[0]["evidence_id"]]}
    envelope_dict = export_research_artifact_envelope(paper=seed, graph_seed=seed, reading_note=note, evidence_spans=evidence, extraction_config={"mode": "fake_llm_no_network", "max_llm_calls": 0}, run_manifest={"network": False, "fake_llm": True})
    envelope = ResearchArtifactEnvelopeV1.from_mapping(envelope_dict)
    imported_note = reading_note_from_envelope(envelope.to_dict())
    feedback = ResearchFeedbackV1.create(source_artifact_id=envelope.artifact_id, canonical_paper_id=envelope.canonical_paper_id, accepted_factors=[{"factor_id": "fake:momentum-cpd", "status": "contract_only"}], metrics={"contract_valid": True}, factor_lineage=[{"parent_evidence_id": evidence[0]["evidence_id"]}], evidence_ids=[evidence[0]["evidence_id"]], recommendations=["run real evaluation only through Slurm"])
    _write(args.output_root / "research_artifact_envelope_v1.json", envelope.to_dict())
    _write(args.output_root / "research_feedback_v1.json", feedback.to_dict())
    summary = {"status": "ok", "network_calls": 0, "fake_llm": True, "canonical_paper_id": envelope.canonical_paper_id, "artifact_id": envelope.artifact_id, "feedback_id": feedback.feedback_id, "imported_reading_note_id": imported_note["reading_note_id"]}
    _write(args.output_root / "summary.json", summary)
    files = [args.output_root / name for name in ("research_artifact_envelope_v1.json", "research_feedback_v1.json", "summary.json")]
    _write(args.output_root / "manifest.json", {"schema_version": "three_project_contract_manifest_v1", "files": [{"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]})
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
