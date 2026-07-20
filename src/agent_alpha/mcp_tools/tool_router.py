from __future__ import annotations

from uuid import uuid4

from agent_alpha.mcp_tools.local_tools import (
    list_fields,
    render_and_compile_candidate_tool,
    render_fac_eval_file,
    search_function_memory_tool,
    search_jsonl,
    search_specialist_agent_memory,
    search_transfer_memory_tool,
    select_mutation_plan_tool,
    validate_factor_fields,
    validate_factor_candidate_tool,
    write_fac_eval_config_tool,
)
from agent_alpha.mcp_tools.permission_guard import assert_tool_allowed
from agent_alpha.mcp_tools.tool_schema import ToolEnvelope


def call_tool(tool_name: str, query: dict, *, role: str) -> dict:
    assert_tool_allowed(role, tool_name)
    if tool_name == "market_data.list_fields":
        results = list_fields(query)
    elif tool_name == "market_data.validate_factor_fields":
        results = validate_factor_fields(query)
    elif tool_name == "factor.validate_candidate":
        results = validate_factor_candidate_tool(query)
    elif tool_name == "factor.render_and_compile_candidate":
        results = render_and_compile_candidate_tool(query)
    elif tool_name == "factor.render_fac_eval_file":
        results = render_fac_eval_file(query)
    elif tool_name == "factor.write_fac_eval_config":
        results = write_fac_eval_config_tool(query)
    elif tool_name == "research_memory.search_chunks":
        results = search_jsonl(query.get("path", "data/document_chunks/missing.jsonl"), str(query.get("query", "")), int(query.get("limit", 10)))
    elif tool_name == "factor_registry.search_factors":
        results = search_jsonl(query.get("path", "data/factor_registry/missing.jsonl"), str(query.get("query", "")), int(query.get("limit", 10)))
    elif tool_name == "evaluation_memory.get_good_bad_memory":
        results = search_jsonl(query.get("path", "data/feedback_memory/missing.jsonl"), str(query.get("query", "")), int(query.get("limit", 10)))
    elif tool_name == "specialist_memory.search":
        results = search_specialist_agent_memory(query)
    elif tool_name == "function_memory.search":
        results = search_function_memory_tool(query)
    elif tool_name == "transfer_memory.search":
        results = search_transfer_memory_tool(query)
    elif tool_name == "mutation_controller.select_plan":
        results = select_mutation_plan_tool(query)
    else:
        raise KeyError(f"unknown tool: {tool_name}")
    return ToolEnvelope(request_id=str(uuid4()), tool_name=tool_name, query=query, results=results, permissions={"role": role}).to_dict()