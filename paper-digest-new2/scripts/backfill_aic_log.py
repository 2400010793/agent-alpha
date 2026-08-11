#!/usr/bin/env python3
"""Backfill structured AIC records from existing proxy traffic logs."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
traffic = ROOT / "logs" / "llm_proxy_traffic.jsonl"
aic = ROOT / "logs" / "llm_aic_calls.jsonl"

def main() -> None:
    if not traffic.exists():
        print(json.dumps({"status": "empty", "reason": "traffic_log_missing"}))
        return
    existing = set()
    if aic.exists():
        for line in aic.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
                if item.get("source_timestamp"):
                    existing.add(item["source_timestamp"])
            except json.JSONDecodeError:
                continue
    rows = []
    for line in traffic.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        timestamp = item.get("timestamp")
        if not timestamp or timestamp in existing:
            continue
        response = item.get("response") if isinstance(item.get("response"), dict) else {}
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        rows.append({
            "call_id": str(uuid.uuid4()),
            "source_timestamp": timestamp,
            "stage": item.get("stage", "unknown"),
            "key_alias": item.get("key_alias", "unknown"),
            "article_id": item.get("article_id", "unknown"),
            "started_at": timestamp,
            "finished_at": timestamp,
            "elapsed_sec": None,
            "upstream_host": item.get("upstream_host", ""),
            "model": item.get("model"),
            "status_code": item.get("status_code"),
            "request": item.get("request"),
            "response": response,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
                "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens")),
                "total_tokens": usage.get("total_tokens"),
            },
            "usage_status": "returned" if usage else "not_returned",
            "status": "ok" if int(item.get("status_code") or 0) in range(200, 300) else "error",
            "backfilled": True,
        })
    if rows:
        aic.parent.mkdir(parents=True, exist_ok=True)
        with aic.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        aic.chmod(0o600)
    print(json.dumps({"status": "ok", "backfilled": len(rows), "output": str(aic)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
