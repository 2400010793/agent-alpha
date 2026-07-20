# Agent Alpha MCP Tool Layer

This directory documents the MCP-style tool interface used by Agent Alpha.

The first implementation is an in-process Python tool router in `src/agent_alpha/mcp_tools/`. Real MCP server wrappers can later delegate to the same functions.

Rules:

- Tools return a standard envelope.
- Tools never expose API keys.
- Market data tools expose field metadata and validation only in this skeleton.
- Research memory tools read local JSON/JSONL memory files only.
- Specialist mutation memory is exposed read-only through `specialist_memory.search`.
- Cog-style function/operator memory is exposed read-only through `function_memory.search`.
- Cog-style mutation transfer memory is exposed read-only through `transfer_memory.search`.
- `mutation_controller.select_plan` is rule-based and does not call an LLM; it returns one parent, one mutation focus, and one specialist agent.