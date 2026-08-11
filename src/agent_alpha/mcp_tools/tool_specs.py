from __future__ import annotations


TOOL_NAME_SEPARATOR = "__"


DESCRIPTIONS = {
    "market_data.list_fields": "Return raw, derived, label, blocked field metadata and allowed functions.",
    "market_data.recommend_fields": "Recommend runtime-safe fields for one AlphaSignal using mechanism tags, signal text, and candidate fields.",
    "market_data.validate_factor_fields": "Validate an expression against field whitelist and label leakage rules.",
    "factor.validate_candidate": "Validate and canonicalize a FactorCandidate JSON object.",
    "factor.render_and_compile_candidate": "Validate, render, and py_compile a FactorCandidate JSON object.",
    "factor.render_fac_eval_file": "Render a validated FactorCandidate to a fac-eval-compatible Python file.",
    "factor.write_fac_eval_config": "Write a fac-eval-demo compatible YAML config for rendered factor files.",
    "research_memory.search_chunks": "Search ingested document chunks by keyword query.",
    "factor_registry.search_factors": "Search stored factor candidate metadata by keyword query.",
    "factor_registry.search_similar_factors": "Search similar historical factors and alpha records for one AlphaSignal.",
    "evaluation_memory.get_good_bad_memory": "Search GOOD/BAD/REVISE feedback memory by keyword query.",
    "specialist_memory.search": "Search compact memory for one specialist mutation agent.",
    "function_memory.search": "Search compact memory about ASL ops, fields, windows, and failure or repair rules.",
    "transfer_memory.search": "Search compact memory about parent-to-child mutation transitions.",
    "mutation_controller.select_plan": "Select one mutation parent and specialist agent without calling an LLM.",
}


PARAMETERS = {
    "market_data.list_fields": {"type": "object", "additionalProperties": False, "properties": {}},
    "market_data.recommend_fields": {
        "type": "object",
        "additionalProperties": False,
        "required": ["signal"],
        "properties": {
            "signal": {"type": "object", "additionalProperties": True},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "runtime_safe_only": {"type": "boolean"},
        },
    },
    "market_data.validate_factor_fields": {
        "type": "object",
        "additionalProperties": False,
        "required": ["expression"],
        "properties": {"expression": {"type": "string"}},
    },
    "factor.validate_candidate": {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidate"],
        "properties": {"candidate": {"type": "object", "additionalProperties": True}},
    },
    "factor.render_and_compile_candidate": {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidate"],
        "properties": {"candidate": {"type": "object", "additionalProperties": True}, "output_dir": {"type": "string"}},
    },
    "factor.render_fac_eval_file": {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidate"],
        "properties": {"candidate": {"type": "object", "additionalProperties": True}, "output_dir": {"type": "string"}},
    },
    "factor.write_fac_eval_config": {
        "type": "object",
        "additionalProperties": False,
        "required": ["factor_files"],
        "properties": {"factor_files": {"type": "array", "items": {"type": "string"}}, "output_path": {"type": "string"}},
    },
    "research_memory.search_chunks": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"path": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
    },
    "factor_registry.search_factors": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"path": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
    },
    "factor_registry.search_similar_factors": {
        "type": "object",
        "additionalProperties": False,
        "required": ["signal"],
        "properties": {
            "signal": {"type": "object", "additionalProperties": True},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "factor_registry_path": {"type": "string"},
            "candidate_sources": {"type": "array", "items": {"type": "string"}},
        },
    },
    "evaluation_memory.get_good_bad_memory": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"path": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
    },
    "specialist_memory.search": {
        "type": "object",
        "additionalProperties": False,
        "required": ["agent_name"],
        "properties": {"agent_name": {"type": "string"}, "query": {"type": "string"}, "root": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
    },
    "function_memory.search": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"path": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
    },
    "transfer_memory.search": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"path": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
    },
    "mutation_controller.select_plan": {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidates"],
        "properties": {
            "candidates": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "feedback_records": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "memory_context": {"type": "object", "additionalProperties": True},
            "lineage_states": {"type": "object", "additionalProperties": True},
            "arm_memory": {"type": "object", "additionalProperties": True},
        },
    },
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
            "parameters": PARAMETERS.get(tool_name, {"type": "object", "description": "Tool query object. Pass exactly the fields required by the tool.", "additionalProperties": True}),
        },
    }


__all__ = ["decode_tool_name", "encode_tool_name", "mcp_tool_spec"]