"""
Graph Grep inspired helper that returns direct neighbors for one or more nodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import BaseModel, Field, validator

from .graph_queries import (
    DEFAULT_GRAPH_PATH,
    aggregate_weight,
    collect_edge_types,
    iter_edge_bundles,
    load_graph_cached,
    matches_attributes,
    node_snapshot,
)


class GetNeighborsInput(BaseModel):
    nodes: List[str] = Field(
        ...,
        min_items=1,
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

    @validator("nodes")
    def _strip_nodes(cls, value: Sequence[str]) -> List[str]:
        cleaned = [str(node).strip() for node in value if str(node).strip()]
        if not cleaned:
            raise ValueError("nodes cannot be empty.")
        return cleaned

    @validator("direction")
    def _validate_direction(cls, value: str) -> str:
        direction = value.lower().strip()
        if direction not in {"in", "out", "all"}:
            raise ValueError("direction must be one of {'in', 'out', 'all'}.")
        return direction


@dataclass(frozen=True)
class GetNeighborsTool:
    graph_path: Path
    name: str = "get_neighbors"
    description: str = (
        "Return the direct neighbors for one or more nodes. Supports inbound, outbound, "
        "or bidirectional traversal as well as filtering by edge type and node attributes."
    )
    args_schema = GetNeighborsInput

    def __post_init__(self) -> None:
        resolved = self.graph_path.expanduser().resolve()
        object.__setattr__(self, "graph_path", resolved)

    def invoke(self, payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
        if isinstance(payload, GetNeighborsInput):
            params = payload
        elif isinstance(payload, Mapping):
            params = self.args_schema(**payload)
        else:
            raise TypeError("Payload must be a mapping or GetNeighborsInput.")
        return self._run(
            nodes=params.nodes,
            direction=params.direction,
            edge_types=params.edge_types,
            filters=params.filter_by_attributes,
            max_neighbors=params.max_neighbors,
        )

    __call__ = invoke

    def _run(
        self,
        *,
        nodes: Sequence[str],
        direction: str,
        edge_types: Optional[Sequence[str]],
        filters: Optional[Mapping[str, Any]],
        max_neighbors: Optional[int],
    ) -> List[Dict[str, Any]]:
        graph = load_graph_cached(self.graph_path)
        summaries: List[Dict[str, Any]] = []
        for node_id in nodes:
            if node_id not in graph:
                summaries.append(
                    {
                        "node_id": node_id,
                        "error": "Node does not exist in the call graph.",
                        "neighbors": [],
                    }
                )
                continue
            neighbors = self._collect_neighbors(
                graph,
                node_id=node_id,
                direction=direction,
                edge_types=edge_types,
                filters=filters,
                max_neighbors=max_neighbors,
            )
            summaries.append({"node_id": node_id, "neighbors": neighbors})
        return summaries

    def _collect_neighbors(
        self,
        graph,
        *,
        node_id: str,
        direction: str,
        edge_types: Optional[Sequence[str]],
        filters: Optional[Mapping[str, Any]],
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
                snapshot.update(
                    {
                        "direction": "outgoing" if dir_key == "out" else "incoming",
                        "edge_types": collect_edge_types(edge_bundle),
                        "edge_count": len(edge_bundle),
                        "weight": aggregate_weight(edge_bundle),
                    }
                )
                payloads.append(snapshot)

        payloads.sort(
            key=lambda entry: (entry.get("weight", 0.0), entry["id"]),
            reverse=True,
        )
        if max_neighbors:
            return payloads[: max_neighbors]
        return payloads


def build_get_neighbors_tool(
    graph_path: Path | str = DEFAULT_GRAPH_PATH,
) -> GetNeighborsTool:
    return GetNeighborsTool(Path(graph_path))


get_neighbors_tool = build_get_neighbors_tool()


__all__ = [
    "GetNeighborsInput",
    "GetNeighborsTool",
    "build_get_neighbors_tool",
    "get_neighbors_tool",
]

