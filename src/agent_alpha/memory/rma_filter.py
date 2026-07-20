from __future__ import annotations


def filter_chunk_feasibility(chunk: dict, allowed_fields: set[str]) -> dict:
    """A-layer feasibility placeholder for document chunks."""
    text = str(chunk.get("text") or "")
    matched = sorted(field for field in allowed_fields if field in text)
    return {"chunk_id": chunk.get("chunk_id"), "decision": "KEEP" if matched else "DROP", "available_proxy_fields": matched}