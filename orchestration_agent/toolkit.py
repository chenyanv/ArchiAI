"""Tool registry for the orchestration agent."""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool

from tools import (
    build_call_graph_pagerank_tool,
    build_extract_subgraph_tool,
    build_find_paths_tool,
    build_get_node_details_tool,
    build_get_source_code_tool,
    build_list_directory_components_tool,
)


def build_orchestration_tools(workspace_id: str, database_url: str | None = None) -> List[BaseTool]:
    """Create all tools available to the orchestration agent.

    The orchestration agent has access to high-level analysis tools
    for understanding the overall architecture of a codebase.
    """
    return [
        # Structure discovery - use this first to understand codebase layout
        build_list_directory_components_tool(workspace_id, database_url),
        # Node importance ranking
        build_call_graph_pagerank_tool(workspace_id, database_url),
        # Exploration tools
        build_extract_subgraph_tool(workspace_id, database_url),
        build_find_paths_tool(workspace_id, database_url),
        build_get_node_details_tool(workspace_id, database_url),
        # Source code inspection
        build_get_source_code_tool(workspace_id, database_url),
    ]


__all__ = ["build_orchestration_tools"]
