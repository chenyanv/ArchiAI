"""Tool registry exposed to the component drilldown agent."""

from __future__ import annotations

from typing import Dict, List, Sequence

from langchain_core.tools import BaseTool

from tools import (
    build_call_graph_pagerank_tool,
    build_evaluate_neighbors_tool,
    build_find_paths_tool,
    build_find_relatives_tool,
    build_get_call_graph_context_tool,
    build_get_neighbors_tool,
    build_get_node_details_tool,
    build_get_source_code_tool,
    build_list_core_models_tool,
    build_list_entry_point_tool,
)


def build_workspace_tools(workspace_id: str, database_url: str | None = None) -> List[BaseTool]:
    """Create all tools bound to a specific workspace."""
    return [
        build_call_graph_pagerank_tool(workspace_id, database_url),
        build_find_paths_tool(workspace_id, database_url),
        build_find_relatives_tool(workspace_id, database_url),
        build_evaluate_neighbors_tool(workspace_id, database_url),
        build_get_neighbors_tool(workspace_id, database_url),
        build_get_node_details_tool(workspace_id, database_url),
        build_get_call_graph_context_tool(workspace_id, database_url),
        build_list_entry_point_tool(workspace_id, database_url),
        build_list_core_models_tool(workspace_id, database_url),
        build_get_source_code_tool(workspace_id, database_url),
    ]


def summarise_tools(tools: Sequence[BaseTool]) -> List[Dict[str, str]]:
    """Return a catalog of tool names and descriptions."""
    return [{"name": getattr(tool, "name", "unknown"), "description": getattr(tool, "description", "")} for tool in tools]


__all__ = ["build_workspace_tools", "summarise_tools"]
