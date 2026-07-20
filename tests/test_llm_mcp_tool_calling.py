from __future__ import annotations

from typing import Any

from agent_alpha.llm.client import LLMClient, LLMSettings


class FakeToolCallingClient(LLMClient):
    def __init__(self) -> None:
        super().__init__(LLMSettings(base_url="https://example.invalid", api_key="fake", model="fake"))
        self.payloads: list[dict[str, Any]] = []

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        if len(self.payloads) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "factor__render_and_compile_candidate",
                                        "arguments": '{"candidate":{"factor_id":"tool_volume","name":"tool_volume","prefix_expression":["zscore","volume",60],"fields":["volume"],"windows":[60],"direction":"positive","mechanism_tags":["trade_impact"]}}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"status":"ok","factor_id":"tool_volume"}',
                    }
                }
            ]
        }


def test_llm_client_can_execute_mcp_tool_call() -> None:
    client = FakeToolCallingClient()

    result = client.complete_json_with_mcp_tools(
        [{"role": "user", "content": "validate this factor"}],
        tool_names=["factor.render_and_compile_candidate"],
        role="The Implementer",
    )

    assert result["status"] == "ok"
    assert result["mcp_tool_events"][0]["tool_name"] == "factor.render_and_compile_candidate"
    assert result["mcp_tool_events"][0]["results"]["ok"] is True
    assert len(client.payloads) == 2
    assert client.payloads[0]["tools"][0]["function"]["name"] == "factor__render_and_compile_candidate"
    assert client.payloads[1]["messages"][-1]["role"] == "tool"