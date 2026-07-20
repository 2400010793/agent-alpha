from __future__ import annotations


TOOL_NAME_SEPARATOR = "__"


DESCRIPTIONS = {
    "market_data.list_fields": "Return raw, derived, label, blocked field metadata and allowed functions.",
    "market_data.validate_factor_fields": "Validate an expression against field whitelist and label leakage rules.",
    "factor.validate_candidate": "Validate and canonicalize a FactorCandidate JSON object.",
    "factor.render_and_compile_candidate": "Validate, render, and py_compile a FactorCandidate JSON object.",
    "factor.render_fac_eval_file": "Render a validated FactorCandidate to a fac-eval-compatible Python file.",
    "factor.write_fac_eval_config": "Write a fac-eval-demo compatible YAML config for rendered factor files.",
    "mutation_controller.select_plan": "Select one mutation parent and specialist agent without calling an LLM.",
}


def encode_tool_name(tool_name: str) -> str:
    return tool_name.replace(".", TOOL_NAME_SEPARATOR)


def decode_tool_name(encoded_name: str) -> str:
    return encoded_name.replace(TOOL_NAME_SEPARATOR, ".")


def mcp_tool_spec(tool_name: str) -> dict:
    """Return an OpenAI-compatible tool spec for an in-process MCP-style tool."""
    return {
        "type": "function",
        "function": {
            "name": encode_tool_name(tool_name),
            "description": DESCRIPTIONS.get(tool_name, f"Call Agent Alpha MCP tool {tool_name}."),
            "parameters": {
                "type": "object",
                "description": "Tool query object. Pass exactly the fields required by the tool.",
                "additionalProperties": True,
            },
        },
    }


__all__ = ["decode_tool_name", "encode_tool_name", "mcp_tool_spec"]