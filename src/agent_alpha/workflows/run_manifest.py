from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_run_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_.-")
    return text or datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")


def default_run_dir(run_type: str, *, run_id: str | None = None, root: str | Path = "outputs/runs") -> Path:
    resolved_run_id = safe_run_id(run_id or f"{run_type}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
    return Path(root) / resolved_run_id


def standard_run_paths(output_dir: str | Path) -> dict[str, Path]:
    root = Path(output_dir)
    return {
        "root": root,
        "manifest": root / "manifest.json",
        "candidates": root / "candidates.jsonl",
        "frontier": root / "frontier.jsonl",
        "lineage_states": root / "lineage_states.json",
        "selection_trace": root / "selection_trace.jsonl",
        "signals": root / "signals.jsonl",
        "evaluations": root / "evaluations.jsonl",
        "function_memory": root / "memory" / "function_memory.jsonl",
        "transfer_memory": root / "memory" / "transfer_memory.jsonl",
        "mutation_arm_memory": root / "memory" / "mutation_arm_memory.jsonl",
        "specialist_memory": root / "memory" / "specialist_memory.jsonl",
        "specialist_memory_dir": root / "memory" / "specialist_agents",
        "rendered": root / "rendered",
        "reports": root / "reports",
    }


def write_json(path: str | Path, payload: Any) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(out)
    return str(out)


def write_jsonl(path: str | Path, records: list[dict[str, Any]], *, append: bool = False) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    target = out if append else out.with_suffix(out.suffix + ".tmp")
    mode = "a" if append else "w"
    with target.open(mode, encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    if not append:
        target.replace(out)
    return str(out)


def append_jsonl(path: str | Path, record: dict[str, Any]) -> str:
    return write_jsonl(path, [record], append=True)


def combine_specialist_memory(output_dir: str | Path) -> str:
    paths = standard_run_paths(output_dir)
    records: list[dict[str, Any]] = []
    specialist_dir = paths["specialist_memory_dir"]
    if specialist_dir.exists():
        for path in sorted(specialist_dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    payload.setdefault("specialist_memory_file", str(path))
                    records.append(payload)
    return write_jsonl(paths["specialist_memory"], records)


def write_run_manifest(
    output_dir: str | Path,
    *,
    run_type: str,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    paths = standard_run_paths(output_dir)
    manifest = {
        "schema_version": "agent_alpha_run_manifest_v1",
        "run_type": run_type,
        "run_id": Path(output_dir).name,
        "created_at": utc_now_iso(),
        "root": str(Path(output_dir)),
        "standard_paths": {key: str(value) for key, value in paths.items() if key != "root"},
        "inputs": inputs or {},
        "outputs": outputs or {},
        "summary": summary or {},
    }
    write_json(paths["manifest"], manifest)
    return manifest


__all__ = [
    "append_jsonl",
    "combine_specialist_memory",
    "default_run_dir",
    "safe_run_id",
    "standard_run_paths",
    "utc_now_iso",
    "write_json",
    "write_jsonl",
    "write_run_manifest",
]
