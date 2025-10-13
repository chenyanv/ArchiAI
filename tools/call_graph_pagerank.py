from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import networkx as nx
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from load_graph import load_graph_from_json

DEFAULT_GRAPH_PATH = Path("results/graphs/call_graph.json")


@lru_cache(maxsize=1)
def _load_cached_graph(path: str) -> nx.DiGraph:
    """Load and cache the call graph to avoid repeated disk I/O."""
    return load_graph_from_json(path)


class PageRankInput(BaseModel):
    limit: int = Field(
        10,
        ge=1,
        le=1000,
        description="Number of top-ranked nodes to return.",
    )


def _compute_pagerank(graph: nx.DiGraph) -> Dict[str, float]:
    """Compute PageRank scores for the provided graph without external deps."""
    if graph.number_of_nodes() == 0:
        return {}

    damping = 0.85
    max_iter = 100
    tol = 1.0e-6

    nodes: List[str] = list(graph.nodes())
    node_count = len(nodes)
    initial_rank = 1.0 / node_count
    ranks: Dict[str, float] = {node: initial_rank for node in nodes}
    dangling_nodes: List[str] = [
        node for node in nodes if graph.out_degree(node) == 0
    ]

    for _ in range(max_iter):
        previous = ranks.copy()
        dangling_contrib = damping * sum(previous[node] for node in dangling_nodes) / node_count

        for node in nodes:
            rank_sum = 0.0
            for predecessor in graph.predecessors(node):
                out_degree = graph.out_degree(predecessor)
                if out_degree:
                    rank_sum += previous[predecessor] / out_degree
            ranks[node] = (
                (1.0 - damping) / node_count
                + damping * rank_sum
                + dangling_contrib
            )

        error = sum(abs(ranks[node] - previous[node]) for node in nodes)
        if error < tol:
            break

    normalisation = sum(ranks.values())
    if normalisation <= 0:
        return ranks
    return {node: score / normalisation for node, score in ranks.items()}


def _format_node_entry(
    node_id: str,
    score: float,
    graph: nx.DiGraph,
) -> Dict[str, Any]:
    """Produce a serialisable representation of a graph node."""
    node_attrs = graph.nodes[node_id]
    return {
        "id": node_id,
        "score": score,
        "label": node_attrs.get("label"),
        "kind": node_attrs.get("kind"),
    }


def build_call_graph_pagerank_tool(
    graph_path: Path | str = DEFAULT_GRAPH_PATH,
) -> StructuredTool:
    """
    Create a LangGraph-compatible tool that returns the top PageRank nodes
    from the cached call graph.
    """
    resolved_path = Path(graph_path).expanduser().resolve()

    def _run(limit: int = 10) -> List[Dict[str, Any]]:
        graph = _load_cached_graph(str(resolved_path))
        scores = _compute_pagerank(graph)
        if not scores:
            return []

        ordered = sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        top_nodes = ordered[:limit]
        return [
            _format_node_entry(node_id, score, graph)
            for node_id, score in top_nodes
        ]

    return StructuredTool.from_function(
        func=_run,
        name="rank_call_graph_nodes",
        description=(
            "Return the top-N call graph nodes ranked by PageRank score. "
            "Useful for identifying high-importance functions or modules."
        ),
        args_schema=PageRankInput,
        return_direct=True,
    )


call_graph_pagerank_tool = build_call_graph_pagerank_tool()
