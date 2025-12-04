"""
Trace simple paths between node sets while respecting call graph edge types.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from langchain_core.tools import tool
from pydantic import BaseModel, Field, validator

from .graph_queries import (
    DEFAULT_GRAPH_PATH,
    EdgeHop,
    iter_neighbors_by_type,
    load_graph_cached,
    node_snapshot,
)

DEFAULT_EDGE_TYPES = ("CALLS", "USES", "DATA_ACCESS")


class FindPathsInput(BaseModel):
    start_nodes: List[str] = Field(
        ...,
        min_items=1,
        description="Entry nodes where traversal begins.",
    )
    end_nodes: List[str] = Field(
        ...,
        min_items=1,
        description="Target nodes that stop traversal when reached.",
    )
    edge_types: Optional[List[str]] = Field(
        default=list(DEFAULT_EDGE_TYPES),
        description="Edge types that are allowed in the traversal.",
    )
    max_depth: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Maximum number of hops in a path (edges).",
    )
    max_paths: int = Field(
        default=25,
        ge=1,
        le=200,
        description="Maximum number of paths to return per start node.",
    )

    @validator("start_nodes", "end_nodes")
    def _strip_nodes(cls, value: Sequence[str]) -> List[str]:
        cleaned = [str(node).strip() for node in value if str(node).strip()]
        if not cleaned:
            raise ValueError("Node lists cannot be empty.")
        return cleaned


def _search_paths(
    graph,
    *,
    start: str,
    targets: Set[str],
    edge_filter: Sequence[str],
    max_depth: int,
    max_paths: int,
) -> List[Dict[str, Any]]:
    if not targets:
        return []

    snapshots_cache: Dict[str, Dict[str, Any]] = {}

    def snapshot(node_id: str) -> Dict[str, Any]:
        if node_id not in snapshots_cache:
            snapshots_cache[node_id] = node_snapshot(graph, node_id)
        return snapshots_cache[node_id]

    stack: List[Tuple[str, List[str], List[str]]] = [(start, [start], [])]
    collected: List[Dict[str, Any]] = []

    if start in targets:
        collected.append(
            {
                "length": 0,
                "nodes": [snapshot(start)],
                "edge_types": [],
            }
        )
        if len(collected) >= max_paths:
            return collected

    while stack:
        current, path_nodes, edge_types_used = stack.pop()
        if len(edge_types_used) >= max_depth:
            continue

        hops = _neighbor_hops(graph, current, edge_filter)
        for hop in hops:
            if hop.neighbor in path_nodes:
                continue
            next_nodes = path_nodes + [hop.neighbor]
            next_edges = edge_types_used + [hop.edge_type]

            if hop.neighbor in targets:
                collected.append(
                    {
                        "length": len(next_edges),
                        "nodes": [snapshot(node) for node in next_nodes],
                        "edge_types": list(next_edges),
                    }
                )
                if len(collected) >= max_paths:
                    return collected

            if len(next_edges) < max_depth:
                stack.append((hop.neighbor, next_nodes, next_edges))

    return collected


def _neighbor_hops(
    graph,
    node_id: str,
    edge_filter: Sequence[str],
) -> Iterable[EdgeHop]:
    return iter_neighbors_by_type(
        graph,
        node_id,
        edge_types=edge_filter,
    )


@tool(args_schema=FindPathsInput)
def find_paths(
    start_nodes: List[str],
    end_nodes: List[str],
    edge_types: Optional[List[str]] = None,
    max_depth: int = 8,
    max_paths: int = 25,
) -> List[Dict[str, Any]]:
    """Return simple paths between the provided start and end node sets.

    Traversal respects the requested edge types and stops once the
    depth or path limits are hit.
    """
    graph = load_graph_cached(DEFAULT_GRAPH_PATH)
    edge_filter = tuple({edge_type.upper() for edge_type in (edge_types or list(DEFAULT_EDGE_TYPES)) if edge_type})
    targets = {node for node in end_nodes if node in graph}

    results: List[Dict[str, Any]] = []
    for start in start_nodes:
        if start not in graph:
            results.append(
                {
                    "start": start,
                    "error": "Node does not exist in the call graph.",
                    "paths": [],
                }
            )
            continue
        paths = _search_paths(
            graph,
            start=start,
            targets=targets,
            edge_filter=edge_filter,
            max_depth=max_depth,
            max_paths=max_paths,
        )
        results.append({"start": start, "paths": paths})
    return results


__all__ = [
    "FindPathsInput",
    "find_paths",
]
