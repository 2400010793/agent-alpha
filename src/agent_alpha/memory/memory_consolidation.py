from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_alpha.memory.function_memory import DEFAULT_FUNCTION_MEMORY_PATH
from agent_alpha.memory.jsonl_store import resolve_store_path, utc_now_iso
from agent_alpha.memory.specialist_memory import DEFAULT_SPECIALIST_MEMORY_DIR, specialist_memory_path
from agent_alpha.memory.transfer_memory import DEFAULT_TRANSFER_MEMORY_PATH


FUNCTION_MEMORY_KEY_FIELDS = ("label", "function_pattern", "condition")
TRANSFER_MEMORY_KEY_FIELDS = ("label", "mutation_type", "from_pattern", "to_pattern")
SPECIALIST_MEMORY_KEY_FIELDS = ("agent_name", "label", "mutation_focus", "parent_factor_id", "child_factor_id")


@dataclass(frozen=True)
class MemoryConsolidationPolicy:
    """Thresholds for deterministic memory compaction.

    The defaults target a small research loop: consolidate after roughly one
    generation of mutations or when compact memory approaches the prompt budget.
    """

    min_records: int = 8
    soft_chars: int = 24_000
    hard_chars: int = 28_000
    max_records_per_store: int = 200


def _json_default(value: Any) -> str:
    return str(value)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    resolved = resolve_store_path(path)
    if not resolved.exists():
        return []
    records: list[dict[str, Any]] = []
    with resolved.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL record must be an object at {resolved}:{line_number}")
            records.append(payload)
    return records


def _write_jsonl(path: str | Path, records: list[dict[str, Any]]) -> None:
    resolved = resolve_store_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = resolved.with_suffix(resolved.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")
    tmp_path.replace(resolved)


def _jsonl_size(path: str | Path) -> tuple[int, int]:
    resolved = resolve_store_path(path)
    if not resolved.exists():
        return 0, 0
    chars = 0
    records = 0
    with resolved.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records += 1
                chars += len(line)
    return records, chars


def _dedupe_list(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _merge_value(existing: Any, value: Any) -> Any:
    if value in (None, "", [], {}):
        return existing
    if existing in (None, "", [], {}):
        return value
    if isinstance(existing, list) or isinstance(value, list):
        left = existing if isinstance(existing, list) else [existing]
        right = value if isinstance(value, list) else [value]
        return _dedupe_list(left + right)
    return existing


def _fingerprint(record: dict[str, Any], key_fields: tuple[str, ...]) -> str:
    if key_fields:
        values = {key: record.get(key) for key in key_fields}
    else:
        values = {key: record.get(key) for key in sorted(record) if key not in {"memory_id", "created_at", "updated_at", "usage_count"}}
    return json.dumps(values, ensure_ascii=False, sort_keys=True, default=_json_default)


def consolidate_memory_records(records: list[dict[str, Any]], *, key_fields: tuple[str, ...], max_records: int | None = None) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = _fingerprint(record, key_fields)
        current = merged.get(key)
        if current is None:
            current = dict(record)
            current.setdefault("usage_count", 0)
            current["occurrence_count"] = max(1, _safe_int(current.get("occurrence_count"), 1))
            current["source_memory_ids"] = [record.get("memory_id")] if record.get("memory_id") else []
            merged[key] = current
            continue
        current["usage_count"] = _safe_int(current.get("usage_count"), 0) + _safe_int(record.get("usage_count"), 0)
        current["occurrence_count"] = _safe_int(current.get("occurrence_count"), 1) + max(1, _safe_int(record.get("occurrence_count"), 1))
        current["source_memory_ids"] = _dedupe_list(list(current.get("source_memory_ids") or []) + ([record.get("memory_id")] if record.get("memory_id") else []))
        for field, value in record.items():
            if field in {"memory_id", "created_at", "updated_at", "usage_count", "occurrence_count", "source_memory_ids"}:
                continue
            current[field] = _merge_value(current.get(field), value)
        if str(record.get("created_at") or "") < str(current.get("created_at") or "~"):
            current["created_at"] = record.get("created_at")
        if str(record.get("updated_at") or record.get("created_at") or "") > str(current.get("updated_at") or current.get("created_at") or ""):
            current["updated_at"] = record.get("updated_at") or record.get("created_at")
    consolidated = list(merged.values())
    consolidated.sort(key=lambda item: (_safe_int(item.get("occurrence_count"), 1), _safe_int(item.get("usage_count"), 0), str(item.get("updated_at") or item.get("created_at") or "")), reverse=True)
    return consolidated[:max_records] if max_records is not None else consolidated


def consolidate_jsonl_memory(path: str | Path, *, key_fields: tuple[str, ...], max_records: int | None = None) -> list[dict[str, Any]]:
    consolidated = consolidate_memory_records(_load_jsonl(path), key_fields=key_fields, max_records=max_records)
    if consolidated:
        now = utc_now_iso()
        for record in consolidated:
            record.setdefault("created_at", now)
            record["updated_at"] = now
        _write_jsonl(path, consolidated)
    return consolidated


def mark_memory_records_used(path: str | Path, memory_ids: list[str], *, amount: int = 1) -> int:
    ids = {str(memory_id) for memory_id in memory_ids if str(memory_id)}
    if not ids:
        return 0
    records = _load_jsonl(path)
    if not records:
        return 0
    now = utc_now_iso()
    updated = 0
    for record in records:
        if str(record.get("memory_id") or "") not in ids:
            continue
        record["usage_count"] = _safe_int(record.get("usage_count"), 0) + amount
        record["updated_at"] = now
        updated += 1
    if updated:
        _write_jsonl(path, records)
    return updated


def consolidate_function_memory(path: str | Path = DEFAULT_FUNCTION_MEMORY_PATH, *, max_records: int | None = None) -> list[dict[str, Any]]:
    return consolidate_jsonl_memory(path, key_fields=FUNCTION_MEMORY_KEY_FIELDS, max_records=max_records)


def consolidate_transfer_memory(path: str | Path = DEFAULT_TRANSFER_MEMORY_PATH, *, max_records: int | None = None) -> list[dict[str, Any]]:
    return consolidate_jsonl_memory(path, key_fields=TRANSFER_MEMORY_KEY_FIELDS, max_records=max_records)


def consolidate_specialist_memory(agent_name: str, root: str | Path = DEFAULT_SPECIALIST_MEMORY_DIR, *, max_records: int | None = None) -> list[dict[str, Any]]:
    return consolidate_jsonl_memory(specialist_memory_path(agent_name, root), key_fields=SPECIALIST_MEMORY_KEY_FIELDS, max_records=max_records)


def should_consolidate_jsonl(path: str | Path, policy: MemoryConsolidationPolicy | None = None) -> bool:
    policy = policy or MemoryConsolidationPolicy()
    records, chars = _jsonl_size(path)
    return records >= policy.min_records or chars >= policy.soft_chars or chars >= policy.hard_chars


def consolidate_mutation_memory_dir(
    root: str | Path,
    *,
    policy: MemoryConsolidationPolicy | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Consolidate specialist/function/transfer stores under one run memory dir.

    `root` is the directory that contains function_memory.jsonl,
    transfer_memory.jsonl, and specialist_agents/*.jsonl. mutation_arm_memory is
    intentionally excluded because selector arm events are aggregated on read.
    """
    policy = policy or MemoryConsolidationPolicy()
    memory_root = resolve_store_path(root)
    summary: dict[str, Any] = {"consolidated": [], "skipped": [], "policy": policy.__dict__}
    stores: list[tuple[str, Path, tuple[str, ...]]] = [
        ("function_memory", memory_root / "function_memory.jsonl", FUNCTION_MEMORY_KEY_FIELDS),
        ("transfer_memory", memory_root / "transfer_memory.jsonl", TRANSFER_MEMORY_KEY_FIELDS),
    ]
    specialist_root = memory_root / "specialist_agents"
    if specialist_root.exists():
        stores.extend((f"specialist_memory:{path.stem}", path, SPECIALIST_MEMORY_KEY_FIELDS) for path in sorted(specialist_root.glob("*.jsonl")))
    for name, path, key_fields in stores:
        before_records, before_chars = _jsonl_size(path)
        if before_records == 0:
            continue
        if not force and not should_consolidate_jsonl(path, policy):
            summary["skipped"].append({"store": name, "records": before_records, "chars": before_chars})
            continue
        records = consolidate_jsonl_memory(path, key_fields=key_fields, max_records=policy.max_records_per_store)
        after_records, after_chars = _jsonl_size(path)
        summary["consolidated"].append(
            {
                "store": name,
                "before_records": before_records,
                "after_records": after_records,
                "before_chars": before_chars,
                "after_chars": after_chars,
                "records_returned": len(records),
            }
        )
    return summary


__all__ = [
    "consolidate_function_memory",
    "consolidate_jsonl_memory",
    "consolidate_memory_records",
    "consolidate_mutation_memory_dir",
    "consolidate_specialist_memory",
    "consolidate_transfer_memory",
    "MemoryConsolidationPolicy",
    "mark_memory_records_used",
    "should_consolidate_jsonl",
]