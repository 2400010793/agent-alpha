from __future__ import annotations

import json


def compact_tool_result(envelope: dict, max_chars: int = 4000) -> str:
    text = json.dumps(envelope, ensure_ascii=False, indent=2)
    return text[:max_chars]