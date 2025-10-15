from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, List

import networkx as nx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from load_graph import load_graph_from_json

DEFAULT_GRAPH_PATH = Path("results/graphs/call_graph.json")


@lru_cache(maxsize=1)
def _load_cached_graph(path: str) -> nx.DiGraph:
    """Load and cache the call graph to avoid repeated disk I/O."""
    return load_graph_from_json(path)


class CallGraphContextInput(BaseModel):
    node_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the call graph node that we want to inspect.",
    )


def _collect_context(graph: nx.DiGraph, node_id: str) -> Dict[str, List[str]]:
    if node_id not in graph:
        raise ValueError(f"Node '{node_id}' does not exist in the call graph.")

    return {
        "calls_to": list(graph.successors(node_id)),
        "called_by": list(graph.predecessors(node_id)),
    }


def build_get_call_graph_context_tool(
    graph_path: Path | str = DEFAULT_GRAPH_PATH,
) -> StructuredTool:
    """
    Create a LangGraph-compatible tool that exposes the immediate neighbourhood of a node.
    """
    resolved_path = Path(graph_path).expanduser().resolve()

    def _run(node_id: str) -> Dict[str, List[str]]:
        graph = _load_cached_graph(str(resolved_path))
        return _collect_context(graph, node_id)

    return StructuredTool.from_function(
        func=_run,
        name="get_call_graph_context",
        description=(
            "Return the direct callees and callers for a node in the call graph. "
            "Useful for graph traversal and for understanding immediate relationships."
        ),
        args_schema=CallGraphContextInput,
        return_direct=True,
    )


call_graph_context_tool = build_get_call_graph_context_tool()
