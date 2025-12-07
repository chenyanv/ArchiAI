"""LangGraph tool for returning the stored attributes of a call graph node."""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from .graph_queries import get_graph


class GetNodeDetailsInput(BaseModel):
    node_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the call graph node whose attributes are needed.",
    )


def _get_node_details_impl(node_id: str, workspace_id: str, database_url: str | None) -> Dict[str, Any]:
    """Core implementation for get_node_details."""
    graph = get_graph(workspace_id, database_url)
    if node_id not in graph:
        raise ValueError(f"Node '{node_id}' does not exist in the call graph.")
    node_attrs = dict(graph.nodes[node_id])
    node_attrs["id"] = node_id
    return node_attrs


def build_get_node_details_tool(workspace_id: str, database_url: str | None = None) -> BaseTool:
    """Create a get_node_details tool bound to a specific workspace."""

    @tool(args_schema=GetNodeDetailsInput)
    def get_node_details(node_id: str) -> Dict[str, Any]:
        """Return the attribute dictionary captured for a call graph node."""
        return _get_node_details_impl(node_id, workspace_id, database_url)

    return get_node_details


__all__ = ["GetNodeDetailsInput", "build_get_node_details_tool"]
