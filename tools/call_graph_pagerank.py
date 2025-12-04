from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import networkx as nx
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from load_graph import DEFAULT_EDGE_WEIGHT
from tools.graph_cache import _load_cached_graph

DEFAULT_GRAPH_PATH = Path("results/graphs/call_graph.json")
WEIGHT_ATTR = "weight"
CATEGORY_RANK_MULTIPLIER: Dict[str, float] = {
    "service": 4.0,
    "controller": 3.5,
    "model": 2.2,
    "data_pipeline": 0.65,
    "integration": 0.5,
    "sdk": 0.5,
    "utility": 0.35,
    "infrastructure": 0.4,
    "test": 0.0,
    "external": 0.0,
    "implementation": 1.0,
    "unknown": 1.0,
}


def _build_call_edge_graph(graph: nx.MultiDiGraph) -> nx.DiGraph:
    """Project the multi-graph onto a weighted DiGraph using CALL edges only."""
    call_graph = nx.DiGraph()
    for node, attrs in graph.nodes(data=True):
        call_graph.add_node(node, **attrs)

    for source, target, data in graph.edges(data=True):
        if data.get("type") != "CALLS":
            continue
        raw_weight = data.get(WEIGHT_ATTR, DEFAULT_EDGE_WEIGHT)
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            weight = float(DEFAULT_EDGE_WEIGHT)
        weight = max(weight, 0.0)
        if call_graph.has_edge(source, target):
            call_graph[source][target][WEIGHT_ATTR] += weight
        else:
            call_graph.add_edge(source, target, **{WEIGHT_ATTR: weight})

    return call_graph


class PageRankInput(BaseModel):
    limit: int = Field(
        10,
        ge=1,
        le=1000,
        description="Number of top-ranked nodes to return.",
    )


def _compute_pagerank(graph: nx.MultiDiGraph) -> Dict[str, float]:
    """Compute PageRank scores for the provided graph using weighted edges."""
    call_graph = _build_call_edge_graph(graph)
    if call_graph.number_of_nodes() == 0:
        return {}

    damping = 0.85
    max_iter = 100
    tol = 1.0e-6

    nodes: List[str] = list(call_graph.nodes())
    node_count = len(nodes)
    initial_rank = 1.0 / node_count
    ranks: Dict[str, float] = {node: initial_rank for node in nodes}

    predecessors: Dict[str, List[str]] = {
        node: list(call_graph.predecessors(node)) for node in nodes
    }
    successors: Dict[str, List[str]] = {
        node: list(call_graph.successors(node)) for node in nodes
    }

    edge_weights: Dict[Tuple[str, str], float] = {}
    out_weight_sum: Dict[str, float] = {}
    for source in nodes:
        total = 0.0
        for target in successors[source]:
            raw_weight = call_graph[source][target].get(WEIGHT_ATTR, DEFAULT_EDGE_WEIGHT)
            try:
                weight = float(raw_weight)
            except (TypeError, ValueError):
                weight = float(DEFAULT_EDGE_WEIGHT)
            if weight < 0.0:
                weight = 0.0
            edge_weights[(source, target)] = weight
            if weight > 0.0:
                total += weight
        out_weight_sum[source] = total

    dangling_nodes: List[str] = [
        node for node, total in out_weight_sum.items() if total <= 0.0
    ]

    for _ in range(max_iter):
        previous = ranks.copy()
        dangling_mass = damping * sum(previous[node] for node in dangling_nodes) / node_count

        for node in nodes:
            rank_sum = 0.0
            for predecessor in predecessors[node]:
                total = out_weight_sum.get(predecessor, 0.0)
                if total <= 0.0:
                    continue
                weight = edge_weights.get((predecessor, node), float(DEFAULT_EDGE_WEIGHT))
                if weight <= 0.0:
                    continue
                rank_sum += previous[predecessor] * (weight / total)
            ranks[node] = (
                (1.0 - damping) / node_count
                + damping * rank_sum
                + dangling_mass
            )

        error = sum(abs(ranks[node] - previous[node]) for node in nodes)
        if error < tol:
            break

    normalisation = sum(ranks.values())
    if normalisation <= 0:
        return ranks

    base_scores = {node: score / normalisation for node, score in ranks.items()}

    adjusted_scores: Dict[str, float] = {}
    for node, score in base_scores.items():
        node_attrs = graph.nodes[node]
        category = node_attrs.get("category") or node_attrs.get("kind")
        multiplier = CATEGORY_RANK_MULTIPLIER.get(category, 1.0)
        adjusted = score * multiplier
        if adjusted <= 0.0:
            continue
        adjusted_scores[node] = adjusted

    if not adjusted_scores:
        return base_scores

    adjusted_total = sum(adjusted_scores.values())
    if adjusted_total <= 0.0:
        return adjusted_scores

    return {node: value / adjusted_total for node, value in adjusted_scores.items()}


def _format_node_entry(
    node_id: str,
    score: float,
    graph: nx.MultiDiGraph,
) -> Dict[str, Any]:
    """Produce a serialisable representation of a graph node."""
    node_attrs = graph.nodes[node_id]
    category = node_attrs.get("category") or node_attrs.get("kind")
    return {
        "id": node_id,
        "score": score,
        "label": node_attrs.get("label"),
        "kind": node_attrs.get("kind"),
        "category": category,
        "file_path": node_attrs.get("file_path"),
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
