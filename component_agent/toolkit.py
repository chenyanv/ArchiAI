"""Tool registry exposed to the component drilldown agent."""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence

from langchain_core.tools import BaseTool

from tools import (
    call_graph_pagerank_tool,
    evaluate_neighbors,
    find_paths,
    find_relatives,
    get_call_graph_context,
    get_neighbors,
    get_node_details,
    get_source_code,
    list_core_models,
    list_entry_point_tool,
)


DEFAULT_SUBAGENT_TOOLS: List[BaseTool] = [
    call_graph_pagerank_tool,
    find_paths,
    find_relatives,
    evaluate_neighbors,
    get_neighbors,
    get_node_details,
    get_call_graph_context,
    list_entry_point_tool,
    list_core_models,
    get_source_code,
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
