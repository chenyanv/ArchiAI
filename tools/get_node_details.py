"""
LangGraph tool for returning the stored attributes of a call graph node.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import networkx as nx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from .graph_cache import _load_cached_graph
from .graph_queries import DEFAULT_GRAPH_PATH


class GetNodeDetailsInput(BaseModel):
    node_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the call graph node whose attributes are needed.",
    )


def _get_node_details(graph: nx.MultiDiGraph, node_id: str) -> Dict[str, Any]:
    if node_id not in graph:
        raise ValueError(f"Node '{node_id}' does not exist in the call graph.")
    node_attrs = dict(graph.nodes[node_id])
    node_attrs.setdefault("id", node_id)
    node_attrs["id"] = node_id
    return node_attrs


@tool(args_schema=GetNodeDetailsInput)
def get_node_details(node_id: str) -> Dict[str, Any]:
    """Return the attribute dictionary captured for a call graph node.

    Returns the data recorded in the call_graph.json export for the specified node.
    """
    graph = _load_cached_graph(str(DEFAULT_GRAPH_PATH))
    return _get_node_details(graph, node_id)


__all__ = [
    "GetNodeDetailsInput",
    "get_node_details",
]
