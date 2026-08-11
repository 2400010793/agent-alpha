import os
import json
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx
from fastapi import FastAPI, Request
from starlette.responses import StreamingResponse

# ---------- Configuration (via env) ----------
UPSTREAM_BASE = os.getenv("PAPER_LLM_BASE_URL", "https://models.github.ai/inference").rstrip("/")
UPSTREAM_API_KEY = os.getenv("PAPER_LLM_API_KEY", "")
LOG_DIR = Path(os.getenv("COPILOT_PROXY_LOG_DIR", "logs"))
MAX_CAPTURE_BYTES = int(os.getenv("COPILOT_PROXY_MAX_CAPTURE_BYTES", str(1_000_000)))  # 1MB
TIMEOUT_SEC = int(os.getenv("PAPER_LLM_TIMEOUT_SEC", "300"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Map short key names (key1/key2/key3) to environment variable names
KEY_ENV_MAP = {
    "key1": "PAPER_LLM_API_KEY",
    "key2": "PAPER_LLM_API_KEY2",
    "key3": "PAPER_LLM_API_KEY3",
}

# Hop-by-hop headers not forwarded/returned
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}

app = FastAPI(title="Copilot Proxy Logger")


def redact_header_value(name: str, value: str) -> str:
    if name.lower() == "authorization":
        return "[REDACTED]"
    return value


def sanitize_headers_for_log(headers: dict) -> dict:
    return {k: redact_header_value(k, v) for k, v in headers.items()}


def extract_usage_from_body(text: str) -> Optional[dict]:
    # Best-effort: parse JSON and pick common usage-like fields
    try:
        j = json.loads(text)
    except Exception:
        return None
    candidates = {}
    for key in ("usage", "billing", "cost", "token_usage", "total_cost"):
        if key in j:
            candidates[key] = j[key]
    # Search nested dicts for token fields
    def scan(d):
        if not isinstance(d, dict):
            return
        for k, v in d.items():
            if isinstance(v, dict):
                if any(x in v for x in ("prompt_tokens", "completion_tokens", "total_tokens", "cost")):
                    candidates[k] = v
                scan(v)
    scan(j)
    return candidates or None


@app.api_route("/proxy/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy(full_path: str, request: Request):
    """
    Forward incoming request to UPSTREAM_BASE/{full_path}, stream response back to caller,
    and capture up to MAX_CAPTURE_BYTES of the response body for logging.

    Supports selecting which upstream API key to use by sending header `X-Use-Key: key1|key2|key3`
    or query param `?use_key=key1`.
    """
    upstream_url = f"{UPSTREAM_BASE}/{full_path}"

    # Read inbound body to forward
    req_body = await request.body()

    # Determine which key to use (incoming header overrides default)
    use_key = None
    if "x-use-key" in request.headers:
        use_key = request.headers.get("x-use-key")
    else:
        use_key = request.query_params.get("use_key")

    # Prepare forward headers: copy but strip hop-by-hop and Host
    forward_headers = {}
    for k, v in request.headers.items():
        if k.lower() in HOP_BY_HOP or k.lower() == "host":
            continue
        forward_headers[k] = v

    # If user requested a specific key, map it to env and set Authorization header
    if use_key:
        env_name = KEY_ENV_MAP.get(use_key)
        if env_name:
            env_val = os.getenv(env_name, "")
            if env_val:
                forward_headers["Authorization"] = f"Bearer {env_val}"
    # Otherwise fallback to default configured key (if any)
    if "Authorization" not in forward_headers and UPSTREAM_API_KEY:
        forward_headers["Authorization"] = f"Bearer {UPSTREAM_API_KEY}"

    timeout = httpx.Timeout(TIMEOUT_SEC, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        upstream_resp = await client.stream(
            request.method,
            upstream_url,
            headers=forward_headers,
            content=req_body,
            params=dict(request.query_params)
        )

        # Response headers to return (filter hop-by-hop)
        response_headers = {k: v for k, v in upstream_resp.headers.items() if k.lower() not in HOP_BY_HOP}

        # Stream generator: yield chunks to client and capture preview
        async def stream_and_capture() -> AsyncIterator[bytes]:
            captured = bytearray()
            try:
                async for chunk in upstream_resp.aiter_bytes():
                    if chunk:
                        # Forward chunk immediately
                        yield chunk
                        # Capture up to limit
                        if len(captured) < MAX_CAPTURE_BYTES:
                            take = min(MAX_CAPTURE_BYTES - len(captured), len(chunk))
                            captured += chunk[:take]
            finally:
                # On completion (or error), write a best-effort log
                log_entry = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "request": {
                        "method": request.method,
                        "path": str(request.url.path),
                        "query": str(request.url.query),
                        "headers": sanitize_headers_for_log(dict(request.headers)),
                    },
                    "upstream": {
                        "url": upstream_url,
                        "status_code": getattr(upstream_resp, "status_code", None),
                        "headers": sanitize_headers_for_log(dict(upstream_resp.headers)),
                    },
                }
                try:
                    preview_text = captured.decode("utf-8", errors="replace")
                    log_entry["captured_bytes"] = len(captured)
                    log_entry["captured_truncated"] = len(captured) >= MAX_CAPTURE_BYTES
                    log_entry["captured_preview"] = preview_text
                    log_entry["extracted_usage"] = extract_usage_from_body(preview_text)
                except Exception as e:
                    log_entry["capture_error"] = str(e)

                fname = LOG_DIR / f"proxy-{datetime.utcnow().strftime('%Y%m%dT%H%M%S%f')}.json"
                try:
                    with fname.open("w", encoding="utf-8") as f:
                        json.dump(log_entry, f, ensure_ascii=False, indent=2)
                except Exception:
                    # best-effort: don't raise on logging failure
                    pass

        return StreamingResponse(stream_and_capture(), status_code=upstream_resp.status_code, headers=response_headers)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "upstream_base": UPSTREAM_BASE}


@app.get("/keys/list")
async def keys_list():
    """Return which configured key env vars exist (do NOT return values)."""
    out = {}
    for short, envn in KEY_ENV_MAP.items():
        out[short] = {"env": envn, "set": bool(os.getenv(envn))}
    # Also include default PAPER_LLM_API_KEY presence
    out["default"] = {"env": "PAPER_LLM_API_KEY", "set": bool(os.getenv("PAPER_LLM_API_KEY"))}
    return out


# ---------- Run with:
# pip install fastapi httpx uvicorn
# uvicorn proxy:app --host 0.0.0.0 --port 8000
#
# Usage examples:
# Use specific key by header:
# curl -v -H "X-Use-Key: key2" -X POST http://localhost:8000/proxy/v1/your/endpoint -d '{"model":"gpt-4o"}'
# or by query param:
# curl -v "http://localhost:8000/proxy/v1/your/endpoint?use_key=key1" -X POST -d '{"model":"gpt-4o"}'
# Check which key envs are set (no secrets returned):
# curl http://localhost:8000/keys/list
