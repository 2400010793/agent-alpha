from __future__ import annotations

from agent_alpha.config import load_yaml


def allowed_tools_for_role(role: str, config_path: str = "configs/mcp_tools.yaml") -> set[str]:
    payload = load_yaml(config_path)
    allowed: set[str] = set()
    for tool in payload.get("tools", []):
        roles = {str(item) for item in tool.get("allowed_roles", [])}
        if role in roles:
            allowed.add(str(tool.get("name")))
    return allowed


def assert_tool_allowed(role: str, tool_name: str) -> None:
    allowed = allowed_tools_for_role(role)
    if tool_name not in allowed:
        raise PermissionError(f"role {role!r} cannot call tool {tool_name!r}")