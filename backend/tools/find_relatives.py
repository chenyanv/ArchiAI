"""Discover ancestors or descendants connected through selected relation types."""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional, Sequence, Set, Tuple

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field, field_validator

from .graph_queries import collect_edge_types, get_graph, iter_edge_bundles, node_snapshot


class FindRelativesInput(BaseModel):
    nodes: List[str] = Field(
        ...,
        min_length=1,
        description="Origin nodes whose relatives should be retrieved.",
    )
    relation_types: List[str] = Field(
        default_factory=lambda: ["CALLS"],
        min_length=1,
        description="Edge types that define the relationship.",
    )
    direction: str = Field(
        default="descendants",
        description="Traversal direction: 'descendants' (default) or 'ancestors'.",
    )
    depth: int = Field(
        default=5,
        ge=1,
        le=15,
        description="Maximum traversal depth.",
    )
    max_relatives: Optional[int] = Field(
        default=50,
        ge=1,
        le=500,
        description="Optional cap on relatives returned per origin node.",
    )

    @field_validator("nodes")
    @classmethod
    def _strip_nodes(cls, value: Sequence[str]) -> List[str]:
        cleaned = [str(node).strip() for node in value if str(node).strip()]
        if not cleaned:
            raise ValueError("nodes cannot be empty.")
        return cleaned

    @field_validator("relation_types")
    @classmethod
    def _strip_relations(cls, value: Sequence[str]) -> List[str]:
        cleaned = [str(edge).strip().upper() for edge in value if str(edge).strip()]
        if not cleaned:
            raise ValueError("relation_types cannot be empty.")
        return cleaned

    @field_validator("direction")
    @classmethod
    def _validate_direction(cls, value: str) -> str:
        direction = value.strip().lower()
        if direction not in {"descendants", "ancestors"}:
            raise ValueError("direction must be 'descendants' or 'ancestors'.")
        return direction


def _neighbor_bundles(
    graph,
    *,
    node_id: str,
    direction: str,
    relation_types: Sequence[str],
) -> List[Tuple[str, List[Any]]]:
    dir_flag = "out" if direction == "descendants" else "in"
    return list(iter_edge_bundles(graph, node_id, direction=dir_flag, edge_types=relation_types))


def _summarise_evidence(bundle: Sequence[Any]) -> Dict[str, Any]:
    metadata = []
    for attrs in bundle:
        entry = {"type": attrs.get("type")}
        for field in ("line", "child_kind", "resolved"):
            if field in attrs:
                entry[field] = attrs[field]
        for list_field in ("call_sites", "usages", "imports", "inheritance"):
            if attrs.get(list_field):
                entry[list_field] = attrs[list_field][:2]
        metadata.append(entry)
    return {"edges": metadata}


def _bfs_relatives(
    graph,
    *,
    start: str,
    direction: str,
    relation_types: Sequence[str],
    depth: int,
    max_relatives: Optional[int],
) -> List[Dict[str, Any]]:
    queue: Deque[Tuple[str, int]] = deque([(start, 0)])
    seen: Dict[str, int] = {start: 0}
    relatives: Dict[str, Dict[str, Any]] = {}

    while queue:
        current, distance = queue.popleft()
        if distance >= depth:
            continue

        for neighbor, bundle in _neighbor_bundles(graph, node_id=current, direction=direction, relation_types=relation_types):
            if neighbor == start:
                continue
            next_distance = distance + 1
            if neighbor in seen and seen[neighbor] <= next_distance:
                continue
            seen[neighbor] = next_distance
            queue.append((neighbor, next_distance))
            summary = relatives.setdefault(
                neighbor,
                {**node_snapshot(graph, neighbor), "distance": next_distance, "edge_types": set(), "evidence": []},
            )
            summary["edge_types"].update(collect_edge_types(bundle))
            summary["evidence"].append(_summarise_evidence(bundle))
            if max_relatives and len(relatives) >= max_relatives:
                break
        if max_relatives and len(relatives) >= max_relatives:
            break

    output = [dict(payload, edge_types=sorted(payload["edge_types"])) for payload in relatives.values()]
    output.sort(key=lambda entry: (entry["distance"], entry["id"]))
    return output[:max_relatives] if max_relatives else output


def _find_relatives_impl(
    nodes: List[str],
    workspace_id: str,
    database_url: str | None,
    relation_types: Optional[List[str]] = None,
    direction: str = "descendants",
    depth: int = 5,
    max_relatives: Optional[int] = 50,
) -> List[Dict[str, Any]]:
    """Core implementation for find_relatives."""
    graph = get_graph(workspace_id, database_url)
    relation_set = tuple({edge.upper() for edge in (relation_types or ["CALLS"])})
    summaries: List[Dict[str, Any]] = []

    for node_id in nodes:
        if node_id not in graph:
            summaries.append({"node_id": node_id, "error": "Node does not exist in the call graph.", "relatives": []})
            continue
        relatives = _bfs_relatives(
            graph, start=node_id, direction=direction, relation_types=relation_set, depth=depth, max_relatives=max_relatives
        )
        summaries.append({"node_id": node_id, "direction": direction, "relatives": relatives})
    return summaries


def build_find_relatives_tool(workspace_id: str, database_url: str | None = None) -> BaseTool:
    """Create a find_relatives tool bound to a specific workspace."""

    @tool(args_schema=FindRelativesInput)
    def find_relatives(
        nodes: List[str],
        relation_types: Optional[List[str]] = None,
        direction: str = "descendants",
        depth: int = 5,
        max_relatives: Optional[int] = 50,
    ) -> List[Dict[str, Any]]:
        """Traverse the call graph to find ancestors or descendants connected by specific relation types."""
        return _find_relatives_impl(nodes, workspace_id, database_url, relation_types, direction, depth, max_relatives)

    return find_relatives


__all__ = ["FindRelativesInput", "build_find_relatives_tool"]
