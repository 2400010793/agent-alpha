from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    api_key: str
    model: str
    timeout_sec: int = 300
    retries: int = 2
    min_interval_sec: float = 10.0


def _first_env(names: list[str], default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def settings_from_env(
    config: dict[str, Any],
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> LLMSettings:
    api_key_names = [str(x) for x in config.get("api_key_envs", [])]
    resolved_api_key = api_key or _first_env(api_key_names)
    if not resolved_api_key:
        raise RuntimeError(f"missing LLM API key; set one of: {', '.join(api_key_names)}")
    resolved_base_url = (base_url or _first_env(
        [str(config.get("base_url_env", "")), str(config.get("fallback_base_url_env", ""))],
        str(config.get("default_base_url", "")),
    )).rstrip("/")
    resolved_model = model or _first_env(
        [str(config.get("model_env", "")), str(config.get("fallback_model_env", ""))],
        str(config.get("default_model", "")),
    )
    timeout_sec = int(_first_env(
        [str(config.get("timeout_sec_env", "")), str(config.get("fallback_timeout_sec_env", ""))],
        str(config.get("default_timeout_sec", 300)),
    ))
    retries = int(_first_env(
        [str(config.get("retries_env", "")), str(config.get("fallback_retries_env", ""))],
        str(config.get("default_retries", 2)),
    ))
    min_interval_sec = float(_first_env(
        [str(config.get("min_interval_sec_env", "")), str(config.get("fallback_min_interval_sec_env", ""))],
        str(config.get("default_min_interval_sec", 10)),
    ))
    return LLMSettings(
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        model=resolved_model,
        timeout_sec=timeout_sec,
        retries=retries,
        min_interval_sec=min_interval_sec,
    )


class LLMClient:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings
        self._last_request_ts = 0.0

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.settings.base_url}/chat/completions"
        last_error: Exception | None = None
        for attempt in range(max(1, self.settings.retries)):
            wait = self.settings.min_interval_sec - (time.time() - self._last_request_ts)
            if wait > 0:
                time.sleep(wait)
            self._last_request_ts = time.time()
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self.settings.timeout_sec)
                response.raise_for_status()
                return response.json()
            except (KeyError, requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < self.settings.retries - 1:
                    time.sleep(min(30.0, 2.0 ** attempt))
        raise RuntimeError(f"LLM request failed: {last_error}")

    def complete(self, messages: list[dict[str, str]], *, response_format: dict[str, str] | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
        }
        if response_format:
            payload["response_format"] = response_format
        data = self._post_chat(payload)
        return str(data["choices"][0]["message"].get("content") or "")

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        content = self.complete(messages, response_format={"type": "json_object"})
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM returned invalid JSON: {content[:500]}") from exc

    def complete_json_with_mcp_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tool_names: list[str],
        role: str,
        max_tool_rounds: int = 4,
    ) -> dict[str, Any]:
        """Complete JSON while allowing the model to call in-process MCP tools."""
        from agent_alpha.mcp_tools.tool_router import call_tool
        from agent_alpha.mcp_tools.tool_specs import decode_tool_name, mcp_tool_spec

        conversation: list[dict[str, Any]] = [dict(message) for message in messages]
        tools = [mcp_tool_spec(tool_name) for tool_name in tool_names]
        tool_events: list[dict[str, Any]] = []
        for _ in range(max_tool_rounds + 1):
            payload: dict[str, Any] = {
                "model": self.settings.model,
                "messages": conversation,
                "tools": tools,
                "tool_choice": "auto",
                "response_format": {"type": "json_object"},
            }
            data = self._post_chat(payload)
            message = dict(data["choices"][0]["message"])
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                content = str(message.get("content") or "")
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"LLM returned invalid JSON after tool calls: {content[:500]}") from exc
                parsed.setdefault("mcp_tool_events", tool_events)
                return parsed
            conversation.append(message)
            for tool_call in tool_calls:
                function = tool_call.get("function") or {}
                encoded_name = str(function.get("name") or "")
                tool_name = decode_tool_name(encoded_name)
                raw_args = function.get("arguments") or "{}"
                try:
                    query = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except (TypeError, json.JSONDecodeError):
                    query = {"_raw_arguments": raw_args}
                try:
                    envelope = call_tool(tool_name, query, role=role)
                except Exception as exc:  # noqa: BLE001 - expose tool failures to the model for repair.
                    envelope = {"tool_name": tool_name, "query": query, "results": {"ok": False, "error": str(exc)}}
                tool_events.append({"tool_name": tool_name, "query": query, "results": envelope.get("results")})
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(tool_call.get("id") or ""),
                        "name": encoded_name,
                        "content": json.dumps(envelope, ensure_ascii=False, default=str),
                    }
                )
        raise RuntimeError("LLM did not produce final JSON after maximum MCP tool rounds")