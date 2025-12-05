"""Action handlers for navigation node actions."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from component_agent import NavigationNode
from component_agent.toolkit import DEFAULT_SUBAGENT_TOOLS
from tools import get_node_details, get_source_code


TOOL_REGISTRY = {tool.name: tool for tool in DEFAULT_SUBAGENT_TOOLS}


def _ensure_database_arg(payload: Dict[str, Any], database_url: Optional[str]) -> Dict[str, Any]:
    if database_url and "database_url" not in payload:
        return {**payload, "database_url": database_url}
    return payload


def handle_inspect_source(target_id: Optional[str], database_url: Optional[str], **_: Any) -> None:
    if not target_id:
        print("No node_id provided for inspect_source.")
        return
    try:
        result = get_source_code.invoke(_ensure_database_arg({"node_id": target_id}, database_url))
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return
    header = f"{result.get('file_path', '')}:{result.get('start_line')}-{result.get('end_line')}"
    print(f"\n=== SOURCE: {header} ===")
    print(result.get("code", "<no code>"))
    print("=== END SOURCE ===")


def handle_inspect_node(target_id: Optional[str], database_url: Optional[str], **_: Any) -> None:
    if not target_id:
        print("No node_id provided for inspect_node.")
        return
    try:
        result = get_node_details.invoke(_ensure_database_arg({"node_id": target_id}, database_url))
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return
    print("\n=== NODE DETAILS ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def handle_inspect_tool(parameters: Dict[str, Any], database_url: Optional[str], **_: Any) -> None:
    tool_name = parameters.get("tool_name")
    if not tool_name or tool_name not in TOOL_REGISTRY:
        print(f"Tool '{tool_name}' not found.")
        return

    tool = TOOL_REGISTRY[tool_name]
    tool_args = dict(parameters.get("tool_args") or {})

    schema = getattr(tool, "args_schema", None)
    if database_url and schema and "database_url" in getattr(schema, "model_fields", {}):
        tool_args.setdefault("database_url", database_url)

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


ACTION_HANDLERS: Dict[str, Callable[..., None]] = {
    "inspect_source": handle_inspect_source,
    "inspect_node": handle_inspect_node,
    "inspect_tool": lambda target_id, database_url, parameters, **_: handle_inspect_tool(parameters, database_url),
    "graph_overlay": lambda target_id, database_url, parameters, **_: handle_graph_overlay(parameters),
}


def execute_action(node: NavigationNode, database_url: Optional[str]) -> None:
    """Execute the action associated with a navigation node."""
    handler = ACTION_HANDLERS.get(node.action.kind)
    if handler:
        handler(
            target_id=node.action.target_id,
            database_url=database_url,
            parameters=node.action.parameters,
        )
    else:
        print(f"Unknown action: '{node.action.kind}'")
