"""Fail-fast readiness check for the frontend-facing Paper Graph backend."""

from __future__ import annotations

import json
import sys
from urllib.error import URLError
from urllib.request import urlopen


BASE_URL = "http://127.0.0.1:8009"


def get(path: str) -> dict:
    with urlopen(BASE_URL + path, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"{path}: HTTP {response.status}")
        return json.load(response)


def main() -> int:
    try:
        ready = get("/api/ready")
        if not ready.get("ready") or not ready.get("graph_sample"):
            raise RuntimeError(f"backend is not ready: {ready}")
        for limit in (20, 40, 80):
            graph = get(f"/api/graphs/realized-volatility?limit={limit}")
            if len(graph.get("nodes", [])) != limit:
                raise RuntimeError(f"limit={limit}: expected {limit} nodes, got {len(graph.get('nodes', []))}")
        print(json.dumps({"ok": True, "base_url": BASE_URL, "limits": [20, 40, 80]}, ensure_ascii=False))
        return 0
    except (OSError, URLError, RuntimeError, ValueError) as error:
        print(json.dumps({"ok": False, "base_url": BASE_URL, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
