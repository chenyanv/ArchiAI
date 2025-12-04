"""Shared graph cache used by all tools to avoid redundant loading."""

from __future__ import annotations

from functools import lru_cache

import networkx as nx

from load_graph import load_graph_from_json

# Global flag to track if we've already loaded the graph once
_GRAPH_LOADED = False


@lru_cache(maxsize=1)
def _load_cached_graph(path: str) -> nx.MultiDiGraph:
    """
    Load and cache the call graph to avoid repeated disk access.

    This is a shared global cache used by all tools. The graph is loaded
    once and then reused across all subsequent tool invocations.
    """
    global _GRAPH_LOADED

    # Only show verbose loading messages on the very first load
    verbose = not _GRAPH_LOADED
    _GRAPH_LOADED = True

    return load_graph_from_json(path, verbose=verbose)
