"""Graph Grep inspired helper that returns direct neighbors for one or more nodes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field, field_validator

from .graph_queries import (
    aggregate_weight,
    collect_edge_types,
    get_graph,
    iter_edge_bundles,
    matches_attributes,
    node_snapshot,
)


class GetNeighborsInput(BaseModel):
    nodes: List[str] = Field(
        ...,
        min_length=1,
        description="List of call graph node identifiers that will act as the origin nodes.",
    )
    direction: str = Field(
        "out",
        description="Traversal direction: 'out', 'in', or 'all'.",
    )
    edge_types: Optional[List[str]] = Field(
        default=None,
        description="Optional subset of edge types to inspect (defaults to all types).",
    )
    filter_by_attributes: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional node attribute filters applied to the neighbors.",
    )
    max_neighbors: Optional[int] = Field(
        default=25,
        ge=1,
        le=500,
        description="Maximum number of neighbors to return per origin node.",
    )

    @field_validator("nodes")
    @classmethod
    def _strip_nodes(cls, value: Sequence[str]) -> List[str]:
        cleaned = [str(node).strip() for node in value if str(node).strip()]
        if not cleaned:
            raise ValueError("nodes cannot be empty.")
        return cleaned

    @field_validator("direction")
    @classmethod
    def _validate_direction(cls, value: str) -> str:
        direction = value.lower().strip()
        if direction not in {"in", "out", "all"}:
            raise ValueError("direction must be one of {'in', 'out', 'all'}.")
        return direction


def _collect_neighbors(
    graph,
    *,
    node_id: str,
    direction: str,
    edge_types: Optional[Sequence[str]],
    filters: Optional[Dict[str, Any]],
    max_neighbors: Optional[int],
) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    directions = (
        ("out",)
        if direction == "out"
        else ("in",) if direction == "in" else ("out", "in")
    )
    for dir_key in directions:
        try:
            bundles = iter_edge_bundles(
                graph,
                node_id,
                direction=dir_key,
                edge_types=edge_types,
            )
        except ValueError:
            continue
        for neighbor_id, edge_bundle in bundles:
            neighbor_attrs = graph.nodes[neighbor_id]
            if not matches_attributes(neighbor_attrs, filters):
                continue
            snapshot = node_snapshot(graph, neighbor_id)
            snapshot.update({
                "direction": "outgoing" if dir_key == "out" else "incoming",
                "edge_types": collect_edge_types(edge_bundle),
                "edge_count": len(edge_bundle),
                "weight": aggregate_weight(edge_bundle),
            })
            payloads.append(snapshot)

    payloads.sort(
        key=lambda entry: (entry.get("weight", 0.0), entry["id"]),
        reverse=True,
    )
    if max_neighbors:
        return payloads[:max_neighbors]
    return payloads


def _get_neighbors_impl(
    nodes: List[str],
    workspace_id: str,
    database_url: str | None,
    direction: str = "out",
    edge_types: Optional[List[str]] = None,
    filter_by_attributes: Optional[Dict[str, Any]] = None,
    max_neighbors: Optional[int] = 25,
) -> List[Dict[str, Any]]:
    """Core implementation for get_neighbors."""
    graph = get_graph(workspace_id, database_url)
    summaries: List[Dict[str, Any]] = []
    for node_id in nodes:
        if node_id not in graph:
            summaries.append({
                "node_id": node_id,
                "error": "Node does not exist in the call graph.",
                "neighbors": [],
            })
            continue
        neighbors = _collect_neighbors(
            graph,
            node_id=node_id,
            direction=direction,
            edge_types=edge_types,
            filters=filter_by_attributes,
            max_neighbors=max_neighbors,
        )
        summaries.append({"node_id": node_id, "neighbors": neighbors})
    return summaries


def build_get_neighbors_tool(workspace_id: str, database_url: str | None = None) -> BaseTool:
    """Create a get_neighbors tool bound to a specific workspace."""

    @tool(args_schema=GetNeighborsInput)
    def get_neighbors(
        nodes: List[str],
        direction: str = "out",
        edge_types: Optional[List[str]] = None,
        filter_by_attributes: Optional[Dict[str, Any]] = None,
        max_neighbors: Optional[int] = 25,
    ) -> List[Dict[str, Any]]:
        """Return the direct neighbors for one or more nodes.

        Supports inbound, outbound, or bidirectional traversal as well as filtering
        by edge type and node attributes.
        """
        return _get_neighbors_impl(
            nodes=nodes,
            workspace_id=workspace_id,
            database_url=database_url,
            direction=direction,
            edge_types=edge_types,
            filter_by_attributes=filter_by_attributes,
            max_neighbors=max_neighbors,
        )

    return get_neighbors


__all__ = [
    "GetNeighborsInput",
    "build_get_neighbors_tool",
]
