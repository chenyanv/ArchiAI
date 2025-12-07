"""LangGraph tool for returning the inbound and outbound call context of a node."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

import networkx as nx
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from .graph_queries import get_graph, normalise_category

DEFAULT_EDGE_WEIGHT = 1.0


def _extract_weight(edge_attrs: Mapping[str, Any]) -> float:
    raw = edge_attrs.get("weight", DEFAULT_EDGE_WEIGHT)
    try:
        weight = float(raw)
    except (TypeError, ValueError):
        weight = DEFAULT_EDGE_WEIGHT
    return max(weight, 0.0)


def _iter_edge_attrs_of_type(graph: nx.MultiDiGraph, source: str, target: str, edge_type: str) -> List[Mapping[str, Any]]:
    data = graph.get_edge_data(source, target)
    if not data:
        return []
    if graph.is_multigraph():
        return [attrs for attrs in data.values() if attrs.get("type") == edge_type]
    if data.get("type") == edge_type:
        return [data]
    return []


def _edge_weight_for_type(graph: nx.MultiDiGraph, source: str, target: str, edge_type: str) -> Optional[float]:
    attrs_list = _iter_edge_attrs_of_type(graph, source, target, edge_type)
    if not attrs_list:
        return None
    return max(_extract_weight(attrs) for attrs in attrs_list)


def _build_neighbor_payload(*, graph: nx.MultiDiGraph, neighbor: str, weight: float, via: Iterable[str] | None = None) -> Dict[str, Any]:
    node_attrs = graph.nodes[neighbor]
    payload = {
        "id": neighbor,
        "label": node_attrs.get("label"),
        "kind": node_attrs.get("kind"),
        "category": normalise_category(node_attrs),
        "file_path": node_attrs.get("file_path"),
        "weight": weight,
    }
    via_nodes = sorted(set(via)) if via else []
    if via_nodes:
        payload["via"] = via_nodes
    return payload


class GetCallGraphContextInput(BaseModel):
    node_id: str = Field(..., min_length=1, description="Identifier of the call graph node to inspect.")


def _iter_file_members(graph: nx.MultiDiGraph, file_path: str) -> Iterable[str]:
    for node, attrs in graph.nodes(data=True):
        if attrs.get("file_path") != file_path or attrs.get("kind") == "file":
            continue
        yield node


def _aggregate_file_neighbors(graph: nx.MultiDiGraph, *, file_path: str, direction: str) -> List[Dict[str, Any]]:
    if not file_path:
        return []

    accumulator: Dict[str, Dict[str, Any]] = {}
    for member in _iter_file_members(graph, file_path):
        if direction == "outgoing":
            iterator = graph.successors(member)
            weight_lookup = lambda n: _edge_weight_for_type(graph, member, n, "CALLS")
        else:
            iterator = graph.predecessors(member)
            weight_lookup = lambda n: _edge_weight_for_type(graph, n, member, "CALLS")

        for neighbor in iterator:
            weight = weight_lookup(neighbor)
            if weight is None or weight < 0.0:
                continue
            payload = accumulator.setdefault(neighbor, {"weight": 0.0, "via": set()})
            payload["weight"] += weight
            payload["via"].add(member)

    results = [
        _build_neighbor_payload(graph=graph, neighbor=n, weight=agg["weight"], via=agg["via"])
        for n, agg in accumulator.items()
    ]
    return sorted(results, key=lambda e: (e.get("weight", 0.0), e["id"]), reverse=True)


def _collect_calls(graph: nx.MultiDiGraph, node_id: str) -> List[Dict[str, Any]]:
    downstream: List[Dict[str, Any]] = []
    for neighbor in graph.successors(node_id):
        call_edges = _iter_edge_attrs_of_type(graph, node_id, neighbor, "CALLS")
        if not call_edges:
            continue
        weight = max(_extract_weight(attrs) for attrs in call_edges)
        downstream.append(_build_neighbor_payload(graph=graph, neighbor=neighbor, weight=weight))

    if downstream:
        return sorted(downstream, key=lambda e: (e.get("weight", 0.0), e["id"]), reverse=True)

    node_attrs = graph.nodes[node_id]
    if node_attrs.get("kind") != "file":
        return []
    return _aggregate_file_neighbors(graph, file_path=node_attrs.get("file_path"), direction="outgoing")


def _collect_callers(graph: nx.MultiDiGraph, node_id: str) -> List[Dict[str, Any]]:
    upstream: List[Dict[str, Any]] = []
    for neighbor in graph.predecessors(node_id):
        call_edges = _iter_edge_attrs_of_type(graph, neighbor, node_id, "CALLS")
        if not call_edges:
            continue
        weight = max(_extract_weight(attrs) for attrs in call_edges)
        upstream.append(_build_neighbor_payload(graph=graph, neighbor=neighbor, weight=weight))

    if upstream:
        return sorted(upstream, key=lambda e: (e.get("weight", 0.0), e["id"]), reverse=True)

    node_attrs = graph.nodes[node_id]
    if node_attrs.get("kind") != "file":
        return []
    return _aggregate_file_neighbors(graph, file_path=node_attrs.get("file_path"), direction="incoming")


def _get_call_graph_context_impl(node_id: str, workspace_id: str, database_url: str | None) -> Dict[str, Any]:
    graph = get_graph(workspace_id, database_url)
    if node_id not in graph:
        raise ValueError(f"Node '{node_id}' does not exist in the call graph.")

    node_attrs = graph.nodes[node_id]
    return {
        "id": node_id,
        "label": node_attrs.get("label"),
        "kind": node_attrs.get("kind"),
        "category": normalise_category(node_attrs),
        "file_path": node_attrs.get("file_path"),
        "calls": _collect_calls(graph, node_id),
        "called_by": _collect_callers(graph, node_id),
    }


def build_get_call_graph_context_tool(workspace_id: str, database_url: str | None = None) -> BaseTool:
    """Create a get_call_graph_context tool bound to a specific workspace."""

    @tool(args_schema=GetCallGraphContextInput)
    def get_call_graph_context(node_id: str) -> Dict[str, Any]:
        """Return call graph context for a node including calls and callers."""
        return _get_call_graph_context_impl(node_id, workspace_id, database_url)

    return get_call_graph_context


__all__ = ["GetCallGraphContextInput", "build_get_call_graph_context_tool"]
