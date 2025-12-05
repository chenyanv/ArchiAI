"""Graph storage and caching for call graphs."""

from __future__ import annotations

from functools import lru_cache

import networkx as nx

from structural_scaffolding.database import CallGraphRecord, create_session


def save_graph(
    workspace_id: str,
    graph: nx.MultiDiGraph,
    database_url: str | None = None,
) -> None:
    """Save a call graph to the database."""
    session = create_session(database_url)
    try:
        data = nx.node_link_data(graph)
        record = CallGraphRecord(
            workspace_id=workspace_id,
            graph_data=data,
            node_count=graph.number_of_nodes(),
            edge_count=graph.number_of_edges(),
        )
        session.merge(record)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def load_graph(
    workspace_id: str,
    database_url: str | None = None,
) -> nx.MultiDiGraph:
    """Load a call graph from the database."""
    session = create_session(database_url)
    try:
        record = session.get(CallGraphRecord, workspace_id)
        if record is None:
            raise ValueError(f"No call graph found for workspace '{workspace_id}'")
        return nx.node_link_graph(record.graph_data)
    finally:
        session.close()


def graph_exists(workspace_id: str, database_url: str | None = None) -> bool:
    """Check if a call graph exists for a workspace."""
    session = create_session(database_url)
    try:
        record = session.get(CallGraphRecord, workspace_id)
        return record is not None
    finally:
        session.close()


# In-memory cache for loaded graphs (keyed by workspace_id + database_url)
@lru_cache(maxsize=8)
def load_graph_cached(workspace_id: str, database_url: str | None = None) -> nx.MultiDiGraph:
    """Load a call graph with caching to avoid repeated database access."""
    return load_graph(workspace_id, database_url)


def clear_graph_cache() -> None:
    """Clear the in-memory graph cache."""
    load_graph_cached.cache_clear()


__all__ = [
    "clear_graph_cache",
    "graph_exists",
    "load_graph",
    "load_graph_cached",
    "save_graph",
]
