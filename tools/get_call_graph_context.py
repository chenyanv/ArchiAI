"""
LangGraph tool for returning the inbound and outbound call context of a node.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

import networkx as nx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from load_graph import DEFAULT_EDGE_WEIGHT
from .graph_cache import _load_cached_graph
from .graph_queries import DEFAULT_GRAPH_PATH


def _normalise_category(node_attrs: Mapping[str, Any]) -> str:
    category = node_attrs.get("category") or node_attrs.get("kind")
    if isinstance(category, str) and category:
        return category
    return "unknown"


def _extract_weight(edge_attrs: Mapping[str, Any]) -> float:
    raw = edge_attrs.get("weight", DEFAULT_EDGE_WEIGHT)
    try:
        weight = float(raw)
    except (TypeError, ValueError):
        weight = float(DEFAULT_EDGE_WEIGHT)
    if weight < 0.0:
        return 0.0
    return weight


def _iter_edge_attrs_of_type(
    graph: nx.MultiDiGraph,
    source: str,
    target: str,
    edge_type: str,
) -> List[Mapping[str, Any]]:
    data = graph.get_edge_data(source, target)
    if not data:
        return []
    if graph.is_multigraph():
        return [attrs for attrs in data.values() if attrs.get("type") == edge_type]
    if data.get("type") == edge_type:
        return [data]
    return []


def _edge_weight_for_type(
    graph: nx.MultiDiGraph,
    source: str,
    target: str,
    edge_type: str,
) -> Optional[float]:
    attrs_list = _iter_edge_attrs_of_type(graph, source, target, edge_type)
    if not attrs_list:
        return None
    return max(_extract_weight(attrs) for attrs in attrs_list)


def _build_neighbor_payload(
    *,
    graph: nx.MultiDiGraph,
    neighbor: str,
    weight: float,
    via: Iterable[str] | None = None,
) -> Dict[str, Any]:
    node_attrs = graph.nodes[neighbor]
    payload = {
        "id": neighbor,
        "label": node_attrs.get("label"),
        "kind": node_attrs.get("kind"),
        "category": _normalise_category(node_attrs),
        "file_path": node_attrs.get("file_path"),
        "weight": weight,
    }
    via_nodes = sorted(set(via)) if via else []
    if via_nodes:
        payload["via"] = via_nodes
    return payload


class GetCallGraphContextInput(BaseModel):
    node_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the call graph node to inspect.",
    )


def _iter_file_members(graph: nx.MultiDiGraph, file_path: str) -> Iterable[str]:
    for node, attrs in graph.nodes(data=True):
        if attrs.get("file_path") != file_path:
            continue
        if attrs.get("kind") == "file":
            continue
        yield node


def _aggregate_file_neighbors(
    graph: nx.MultiDiGraph,
    *,
    file_path: str,
    direction: str,
) -> List[Dict[str, Any]]:
    if not file_path:
        return []

    accumulator: Dict[str, Dict[str, Any]] = {}

    for member in _iter_file_members(graph, file_path):
        if direction == "outgoing":
            iterator = graph.successors(member)
            weight_lookup = lambda neighbor: _edge_weight_for_type(graph, member, neighbor, "CALLS")
        else:
            iterator = graph.predecessors(member)
            weight_lookup = lambda neighbor: _edge_weight_for_type(graph, neighbor, member, "CALLS")

        for neighbor in iterator:
            weight = weight_lookup(neighbor)
            if weight is None:
                continue
            if weight < 0.0:
                continue
            payload = accumulator.setdefault(
                neighbor,
                {"weight": 0.0, "via": set()},
            )
            payload["weight"] += weight
            payload["via"].add(member)

    results: List[Dict[str, Any]] = []
    for neighbor, aggregated in accumulator.items():
        via_nodes: Set[str] = aggregated["via"]
        entry = _build_neighbor_payload(
            graph=graph,
            neighbor=neighbor,
            weight=aggregated["weight"],
            via=via_nodes,
        )
        results.append(entry)

    return sorted(
        results,
        key=lambda entry: (entry.get("weight", 0.0), entry["id"]),
        reverse=True,
    )


def _collect_calls(graph: nx.MultiDiGraph, node_id: str) -> List[Dict[str, Any]]:
    downstream: List[Dict[str, Any]] = []
    for neighbor in graph.successors(node_id):
        call_edges = _iter_edge_attrs_of_type(graph, node_id, neighbor, "CALLS")
        if not call_edges:
            continue
        weight = max(_extract_weight(attrs) for attrs in call_edges)
        downstream.append(
            _build_neighbor_payload(
                graph=graph,
                neighbor=neighbor,
                weight=weight,
                via=None,
            )
        )

    if downstream:
        return sorted(
            downstream,
            key=lambda entry: (entry.get("weight", 0.0), entry["id"]),
            reverse=True,
        )

    node_attrs = graph.nodes[node_id]
    if node_attrs.get("kind") != "file":
        return []

    file_path = node_attrs.get("file_path")
    return _aggregate_file_neighbors(
        graph,
        file_path=file_path,
        direction="outgoing",
    )


def _collect_callers(graph: nx.MultiDiGraph, node_id: str) -> List[Dict[str, Any]]:
    upstream: List[Dict[str, Any]] = []
    for neighbor in graph.predecessors(node_id):
        call_edges = _iter_edge_attrs_of_type(graph, neighbor, node_id, "CALLS")
        if not call_edges:
            continue
        weight = max(_extract_weight(attrs) for attrs in call_edges)
        upstream.append(
            _build_neighbor_payload(
                graph=graph,
                neighbor=neighbor,
                weight=weight,
                via=None,
            )
        )

    if upstream:
        return sorted(
            upstream,
            key=lambda entry: (entry.get("weight", 0.0), entry["id"]),
            reverse=True,
        )

    node_attrs = graph.nodes[node_id]
    if node_attrs.get("kind") != "file":
        return []

    file_path = node_attrs.get("file_path")
    return _aggregate_file_neighbors(
        graph,
        file_path=file_path,
        direction="incoming",
    )


@tool(args_schema=GetCallGraphContextInput)
def get_call_graph_context(node_id: str) -> Dict[str, Any]:
    """Return the call graph context for a node.

    Includes the downstream calls it makes and the upstream callers that reference it.
    """
    graph = _load_cached_graph(str(DEFAULT_GRAPH_PATH))
    if node_id not in graph:
        raise ValueError(f"Node '{node_id}' does not exist in the call graph.")

    node_attrs = graph.nodes[node_id]
    payload = {
        "id": node_id,
        "label": node_attrs.get("label"),
        "kind": node_attrs.get("kind"),
        "category": _normalise_category(node_attrs),
        "file_path": node_attrs.get("file_path"),
        "calls": _collect_calls(graph, node_id),
        "called_by": _collect_callers(graph, node_id),
    }
    return payload


__all__ = [
    "GetCallGraphContextInput",
    "get_call_graph_context",
]
