"""
LangGraph tool for returning the stored attributes of a call graph node.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping

import networkx as nx
from pydantic import BaseModel, Field

from load_graph import load_graph_from_json

DEFAULT_GRAPH_PATH = Path("results/graphs/call_graph.json")


@lru_cache(maxsize=1)
def _load_cached_graph(path: str) -> nx.MultiDiGraph:
    """Load and cache the call graph to minimise repeated disk access."""
    return load_graph_from_json(path)


class GetNodeDetailsInput(BaseModel):
    node_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the call graph node whose attributes are needed.",
    )


@dataclass(frozen=True)
class GetNodeDetailsTool:
    """
    Look up the stored call graph attributes for a single node.
    """

    graph_path: Path
    name: str = "get_node_details"
    description: str = (
        "Return the attribute dictionary captured for a call graph node, "
        "matching the data recorded in the call_graph.json export."
    )
    args_schema = GetNodeDetailsInput

    def __post_init__(self) -> None:
        resolved = self.graph_path.expanduser().resolve()
        object.__setattr__(self, "graph_path", resolved)

    def _run(self, node_id: str) -> Dict[str, Any]:
        graph = _load_cached_graph(str(self.graph_path))
        if node_id not in graph:
            raise ValueError(f"Node '{node_id}' does not exist in the call graph.")
        node_attrs = dict(graph.nodes[node_id])
        node_attrs.setdefault("id", node_id)
        node_attrs["id"] = node_id
        return node_attrs

    def invoke(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        if isinstance(payload, GetNodeDetailsInput):
            params = payload
        elif isinstance(payload, Mapping):
            params = self.args_schema(**payload)
        else:
            raise TypeError("Tool payload must be a mapping or GetNodeDetailsInput.")
        return self._run(params.node_id)

    def __call__(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        return self.invoke(payload)


def build_get_node_details_tool(
    graph_path: Path | str = DEFAULT_GRAPH_PATH,
) -> GetNodeDetailsTool:
    """
    Create a LangGraph-compatible tool for fetching node attribute metadata.
    """
    return GetNodeDetailsTool(Path(graph_path))


get_node_details_tool = build_get_node_details_tool()


__all__ = [
    "GetNodeDetailsInput",
    "GetNodeDetailsTool",
    "build_get_node_details_tool",
    "get_node_details_tool",
]
