"""
Discover ancestors or descendants connected through selected relation types.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Set, Tuple

from collections import deque

from langchain_core.tools import tool
from pydantic import BaseModel, Field, validator

from .graph_queries import (
    collect_edge_types,
    iter_edge_bundles,
    load_graph_cached,
    node_snapshot,
)


class FindRelativesInput(BaseModel):
    nodes: List[str] = Field(
        ...,
        min_items=1,
        description="Origin nodes whose relatives should be retrieved.",
    )
    relation_types: List[str] = Field(
        default_factory=lambda: ["CALLS"],
        min_items=1,
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

    @validator("nodes")
    def _strip_nodes(cls, value: Sequence[str]) -> List[str]:
        cleaned = [str(node).strip() for node in value if str(node).strip()]
        if not cleaned:
            raise ValueError("nodes cannot be empty.")
        return cleaned

    @validator("relation_types")
    def _strip_relations(cls, value: Sequence[str]) -> List[str]:
        cleaned = [str(edge).strip().upper() for edge in value if str(edge).strip()]
        if not cleaned:
            raise ValueError("relation_types cannot be empty.")
        return cleaned

    @validator("direction")
    def _validate_direction(cls, value: str) -> str:
        direction = value.strip().lower()
        if direction not in {"descendants", "ancestors"}:
            raise ValueError("direction must be 'descendants' or 'ancestors'.")
        return direction


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

        bundles = _neighbor_bundles(
            graph,
            node_id=current,
            direction=direction,
            relation_types=relation_types,
        )
        for neighbor, bundle in bundles:
            if neighbor == start:
                continue
            next_distance = distance + 1
            if neighbor in seen and seen[neighbor] <= next_distance:
                continue
            seen[neighbor] = next_distance
            queue.append((neighbor, next_distance))
            summary = relatives.setdefault(
                neighbor,
                {
                    **node_snapshot(graph, neighbor),
                    "distance": next_distance,
                    "edge_types": set(),
                    "evidence": [],
                },
            )
            summary["edge_types"].update(collect_edge_types(bundle))
            summary["evidence"].append(_summarise_evidence(bundle))
            if max_relatives and len(relatives) >= max_relatives:
                break
        if max_relatives and len(relatives) >= max_relatives:
            break

    output: List[Dict[str, Any]] = []
    for payload in relatives.values():
        payload["edge_types"] = sorted(payload["edge_types"])
        output.append(payload)

    output.sort(key=lambda entry: (entry["distance"], entry["id"]))
    if max_relatives:
        return output[: max_relatives]
    return output


def _neighbor_bundles(
    graph,
    *,
    node_id: str,
    direction: str,
    relation_types: Sequence[str],
) -> List[Tuple[str, List[Any]]]:
    dir_flag = "out" if direction == "descendants" else "in"
    bundles = iter_edge_bundles(
        graph,
        node_id,
        direction=dir_flag,
        edge_types=relation_types,
    )
    return list(bundles)


def _summarise_evidence(bundle: Sequence[Any]) -> Dict[str, Any]:
    metadata = []
    for attrs in bundle:
        entry = {"type": attrs.get("type")}
        for field in ("line", "child_kind", "resolved"):
            if field in attrs:
                entry[field] = attrs[field]
        if attrs.get("call_sites"):
            entry["call_sites"] = attrs["call_sites"][:2]
        if attrs.get("usages"):
            entry["usages"] = attrs["usages"][:2]
        if attrs.get("imports"):
            entry["imports"] = attrs["imports"][:2]
        if attrs.get("inheritance"):
            entry["inheritance"] = attrs["inheritance"][:2]
        metadata.append(entry)
    return {"edges": metadata}


@tool(args_schema=FindRelativesInput)
def find_relatives(
    nodes: List[str],
    relation_types: List[str] = None,
    direction: str = "descendants",
    depth: int = 5,
    max_relatives: Optional[int] = 50,
) -> List[Dict[str, Any]]:
    """Traverse the call graph to find ancestors or descendants that are connected by specific relation types.

    Supports various relation types including CALLS, INHERITS_FROM, and CONTAINS.
    """
    if relation_types is None:
        relation_types = ["CALLS"]
    graph = load_graph_cached(None)
    relation_set = tuple({edge.upper() for edge in relation_types})
    summaries: List[Dict[str, Any]] = []

    for node_id in nodes:
        if node_id not in graph:
            summaries.append(
                {
                    "node_id": node_id,
                    "error": "Node does not exist in the call graph.",
                    "relatives": [],
                }
            )
            continue
        relatives = _bfs_relatives(
            graph,
            start=node_id,
            direction=direction,
            relation_types=relation_set,
            depth=depth,
            max_relatives=max_relatives,
        )
        summaries.append(
            {
                "node_id": node_id,
                "direction": direction,
                "relatives": relatives,
            }
        )
    return summaries


__all__ = [
    "FindRelativesInput",
    "find_relatives",
]

