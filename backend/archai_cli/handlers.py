"""Action handlers for navigation node actions."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from component_agent import NavigationNode
from component_agent.toolkit import build_workspace_tools
from tools import build_get_source_code_tool


def handle_inspect_source(
    target_id: Optional[str],
    workspace_id: str,
    database_url: Optional[str],
    **_: Any,
) -> None:
    if not target_id:
        print("No node_id provided for inspect_source.")
        return
    tool = build_get_source_code_tool(workspace_id, database_url)
    try:
        result = tool.invoke({"node_id": target_id})
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return
    header = f"{result.get('file_path', '')}:{result.get('start_line')}-{result.get('end_line')}"
    print(f"\n=== SOURCE: {header} ===")
    print(result.get("code", "<no code>"))
    print("=== END SOURCE ===")


def handle_inspect_tool(
    parameters: Dict[str, Any],
    workspace_id: str,
    database_url: Optional[str],
    **_: Any,
) -> None:
    tool_name = parameters.get("tool_name")
    if not tool_name:
        print("No tool_name provided.")
        return

    # Build tools for this workspace and find the requested tool
    tools = build_workspace_tools(workspace_id, database_url)
    tool_registry = {tool.name: tool for tool in tools}

    if tool_name not in tool_registry:
        print(f"Tool '{tool_name}' not found.")
        return

    tool = tool_registry[tool_name]
    tool_args = dict(parameters.get("tool_args") or {})

    try:
        result = tool.invoke(tool_args)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return
    print(f"\n=== TOOL RESULT ({tool_name}) ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def handle_graph_overlay(parameters: Dict[str, Any], **_: Any) -> None:
    print("\n=== GRAPH OVERLAY REQUEST ===")
    print(json.dumps(parameters or {}, ensure_ascii=False, indent=2))
    print("(Render in frontend graph viewer.)")


def execute_action(node: NavigationNode, workspace_id: str, database_url: Optional[str]) -> None:
    """Execute the action associated with a navigation node."""
    kind = node.action.kind
    target_id = node.action.target_id
    parameters = node.action.parameters

    if kind == "inspect_source":
        handle_inspect_source(target_id, workspace_id, database_url)
    elif kind == "inspect_tool":
        handle_inspect_tool(parameters, workspace_id, database_url)
    elif kind == "graph_overlay":
        handle_graph_overlay(parameters)
    else:
        print(f"Unknown action: '{kind}'")
