"""Common graph query utilities used by tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

import networkx as nx

from tools.graph_cache import load_graph_cached


def get_graph(workspace_id: str, database_url: str | None = None) -> nx.MultiDiGraph:
    """Get the call graph for a workspace."""
    return load_graph_cached(workspace_id, database_url)


def normalise_category(attrs: Mapping[str, Any]) -> str:
    category = attrs.get("category") or attrs.get("kind")
    if isinstance(category, str) and category:
        return category
    return "unknown"


def node_snapshot(graph: nx.MultiDiGraph, node_id: str, workspace_id: str | None = None, database_url: str | None = None) -> Dict[str, Any]:
    """Create a snapshot of a node's metadata, including docstring/summary.

    First tries to get data from the graph. If node not found in graph,
    falls back to ProfileRecord to handle cases where node exists in database
    but was filtered from the call graph.

    Args:
        graph: The call graph
        node_id: The node ID to snapshot
        workspace_id: Required if node might not be in graph (for ProfileRecord lookup)
        database_url: Database URL for ProfileRecord lookup

    Returns:
        Dict with fields: id, label, kind, category, file_path, summary (optional)
    """
    # Try graph first
    if node_id in graph.nodes:
        attrs = graph.nodes[node_id]
        snapshot = {
            "id": node_id,
            "label": attrs.get("label"),
            "kind": attrs.get("kind"),
            "category": normalise_category(attrs),
            "file_path": attrs.get("file_path"),
        }
        # Include summary if available in graph attributes
        summary = attrs.get("summary") or attrs.get("docstring")
        if summary:
            snapshot["summary"] = summary
        return snapshot

    # Fallback: try ProfileRecord if node not in graph
    if workspace_id and database_url:
        try:
            from structural_scaffolding.database import ProfileRecord, create_session
            from sqlalchemy import select

            session = create_session(database_url)
            try:
                stmt = select(ProfileRecord).where(
                    ProfileRecord.workspace_id == workspace_id,
                    ProfileRecord.id == node_id,
                )
                record = session.execute(stmt).scalar_one_or_none()
                if record:
                    snapshot = {
                        "id": node_id,
                        "label": f"{record.class_name or ''}{':' if record.class_name and record.function_name else ''}{record.function_name or record.class_name or 'unknown'}",
                        "kind": record.kind,
                        "category": "implementation",  # Default category for ProfileRecord lookups
                        "file_path": record.file_path,
                    }
                    # Include docstring from database as summary
                    if record.docstring:
                        snapshot["summary"] = record.docstring
                    return snapshot
            finally:
                session.close()
        except Exception:
            # If ProfileRecord lookup fails, continue to raise KeyError
            pass

    # Node not found anywhere
    raise KeyError(f"Node '{node_id}' not found in graph or database")


def _match_value(value: Any, expected: Any) -> bool:
    if isinstance(expected, (list, tuple, set)):
        expected_values = {str(item).lower() for item in expected if item is not None}
        return str(value).lower() in expected_values
    if expected is None:
        return value is None
    return str(value).lower() == str(expected).lower()


def matches_attributes(attrs: Mapping[str, Any], filters: Optional[Mapping[str, Any]]) -> bool:
    if not filters:
        return True
    for key, expected in filters.items():
        if key not in attrs:
            return False
        if not _match_value(attrs.get(key), expected):
            return False
    return True


def _edge_passes(edge_attrs: Mapping[str, Any], allowed_types: Optional[Set[str]]) -> bool:
    if not allowed_types:
        return True
    edge_type = str(edge_attrs.get("type") or "").upper()
    return edge_type in allowed_types


def iter_edge_bundles(
    graph: nx.MultiDiGraph,
    node_id: str,
    *,
    direction: str,
    edge_types: Optional[Sequence[str]] = None,
) -> Iterator[Tuple[str, List[Mapping[str, Any]]]]:
    """Yield (neighbor_id, edge_attrs_list) tuples for inbound or outbound edges."""
    if node_id not in graph:
        return

    allowed_types = {edge_type.upper() for edge_type in edge_types} if edge_types else None

    if direction == "in":
        iterator = graph.predecessors(node_id)
        accessor = lambda neighbor: graph.get_edge_data(neighbor, node_id) or {}
    elif direction == "out":
        iterator = graph.successors(node_id)
        accessor = lambda neighbor: graph.get_edge_data(node_id, neighbor) or {}
    else:
        raise ValueError(f"Unsupported direction '{direction}'. Expected 'in' or 'out'.")

    for neighbor in iterator:
        attrs_map = accessor(neighbor)
        bundle = [
            attrs
            for attrs in _iter_attrs(attrs_map)
            if _edge_passes(attrs, allowed_types)
        ]
        if bundle:
            yield neighbor, bundle


def _iter_attrs(edge_dict: Mapping[str, Mapping[str, Any]]) -> Iterable[Mapping[str, Any]]:
    if isinstance(edge_dict, MutableMapping):
        for attrs in edge_dict.values():
            if isinstance(attrs, Mapping):
                yield attrs


def aggregate_weight(bundle: Iterable[Mapping[str, Any]]) -> float:
    total = 0.0
    for attrs in bundle:
        weight = attrs.get("weight")
        try:
            value = float(weight)
        except (TypeError, ValueError):
            value = 0.0
        total += max(value, 0.0)
    return total


def collect_edge_types(bundle: Iterable[Mapping[str, Any]]) -> List[str]:
    types: Set[str] = set()
    for attrs in bundle:
        edge_type = attrs.get("type")
        if edge_type:
            types.add(str(edge_type).upper())
    return sorted(types)


@dataclass(frozen=True)
class EdgeHop:
    neighbor: str
    edge_type: str


def iter_neighbors_by_type(
    graph: nx.MultiDiGraph,
    node_id: str,
    *,
    edge_types: Optional[Sequence[str]] = None,
) -> Iterator[EdgeHop]:
    allowed = {edge_type.upper() for edge_type in edge_types} if edge_types else None
    for neighbor in graph.successors(node_id):
        edge_data = graph.get_edge_data(node_id, neighbor) or {}
        for attrs in _iter_attrs(edge_data):
            edge_type = str(attrs.get("type") or "").upper()
            if allowed and edge_type not in allowed:
                continue
            yield EdgeHop(neighbor=neighbor, edge_type=edge_type)
