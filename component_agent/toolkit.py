"""Tool registry exposed to the component drilldown agent."""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence

from langchain_core.tools import BaseTool

from tools import (
    call_graph_pagerank_tool,
    evaluate_neighbors_tool,
    find_paths_tool,
    find_relatives_tool,
    get_call_graph_context_tool,
    get_neighbors_tool,
    get_node_details_tool,
    get_source_code_tool,
    list_core_models,
    list_entry_point_tool,
)


DEFAULT_SUBAGENT_TOOLS: List[BaseTool] = [
    call_graph_pagerank_tool,
    find_paths_tool,
    find_relatives_tool,
    evaluate_neighbors_tool,
    get_neighbors_tool,
    get_node_details_tool,
    get_call_graph_context_tool,
    list_entry_point_tool,
    list_core_models,
    get_source_code_tool,
]


def summarise_tools(tools: Sequence[BaseTool]) -> List[Dict[str, str]]:
    catalog: List[Dict[str, str]] = []
    for tool in tools:
        catalog.append({
            "name": getattr(tool, "name", "unknown"),
            "description": getattr(tool, "description", ""),
        })
    return catalog


__all__ = ["DEFAULT_SUBAGENT_TOOLS", "summarise_tools"]
