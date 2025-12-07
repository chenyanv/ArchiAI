"""PageRank-based ranking for call graph nodes."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import networkx as nx
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from .graph_queries import get_graph, normalise_category

DEFAULT_EDGE_WEIGHT = 1.0
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


class PageRankInput(BaseModel):
    limit: int = Field(10, ge=1, le=1000, description="Number of top-ranked nodes to return.")


def _build_call_edge_graph(graph: nx.MultiDiGraph) -> nx.DiGraph:
    """Project the multi-graph onto a weighted DiGraph using CALL edges only."""
    call_graph = nx.DiGraph()
    for node, attrs in graph.nodes(data=True):
        call_graph.add_node(node, **attrs)

    for source, target, data in graph.edges(data=True):
        if data.get("type") != "CALLS":
            continue
        try:
            weight = max(float(data.get(WEIGHT_ATTR, DEFAULT_EDGE_WEIGHT)), 0.0)
        except (TypeError, ValueError):
            weight = DEFAULT_EDGE_WEIGHT

        if call_graph.has_edge(source, target):
            call_graph[source][target][WEIGHT_ATTR] += weight
        else:
            call_graph.add_edge(source, target, **{WEIGHT_ATTR: weight})

    return call_graph


def _compute_pagerank(graph: nx.MultiDiGraph) -> Dict[str, float]:
    """Compute PageRank scores with category-based adjustments."""
    call_graph = _build_call_edge_graph(graph)
    if call_graph.number_of_nodes() == 0:
        return {}

    damping, max_iter, tol = 0.85, 100, 1.0e-6
    nodes = list(call_graph.nodes())
    node_count = len(nodes)
    ranks = {node: 1.0 / node_count for node in nodes}

    predecessors = {node: list(call_graph.predecessors(node)) for node in nodes}
    successors = {node: list(call_graph.successors(node)) for node in nodes}

    edge_weights: Dict[Tuple[str, str], float] = {}
    out_weight_sum: Dict[str, float] = {}
    for source in nodes:
        total = 0.0
        for target in successors[source]:
            try:
                weight = max(float(call_graph[source][target].get(WEIGHT_ATTR, DEFAULT_EDGE_WEIGHT)), 0.0)
            except (TypeError, ValueError):
                weight = DEFAULT_EDGE_WEIGHT
            edge_weights[(source, target)] = weight
            if weight > 0.0:
                total += weight
        out_weight_sum[source] = total

    dangling_nodes = [node for node, total in out_weight_sum.items() if total <= 0.0]

    for _ in range(max_iter):
        previous = ranks.copy()
        dangling_mass = damping * sum(previous[node] for node in dangling_nodes) / node_count

        for node in nodes:
            rank_sum = 0.0
            for pred in predecessors[node]:
                total = out_weight_sum.get(pred, 0.0)
                if total <= 0.0:
                    continue
                weight = edge_weights.get((pred, node), DEFAULT_EDGE_WEIGHT)
                if weight > 0.0:
                    rank_sum += previous[pred] * (weight / total)
            ranks[node] = (1.0 - damping) / node_count + damping * rank_sum + dangling_mass

        if sum(abs(ranks[n] - previous[n]) for n in nodes) < tol:
            break

    # Normalize and apply category multipliers
    normalisation = sum(ranks.values())
    if normalisation <= 0:
        return ranks

    base_scores = {node: score / normalisation for node, score in ranks.items()}
    adjusted_scores = {}
    for node, score in base_scores.items():
        category = normalise_category(graph.nodes[node])
        multiplier = CATEGORY_RANK_MULTIPLIER.get(category, 1.0)
        adjusted = score * multiplier
        if adjusted > 0.0:
            adjusted_scores[node] = adjusted

    if not adjusted_scores:
        return base_scores

    adjusted_total = sum(adjusted_scores.values())
    return {node: value / adjusted_total for node, value in adjusted_scores.items()} if adjusted_total > 0 else adjusted_scores


def _format_node_entry(node_id: str, score: float, graph: nx.MultiDiGraph) -> Dict[str, Any]:
    node_attrs = graph.nodes[node_id]
    return {
        "id": node_id,
        "score": score,
        "label": node_attrs.get("label"),
        "kind": node_attrs.get("kind"),
        "category": normalise_category(node_attrs),
        "file_path": node_attrs.get("file_path"),
    }


def build_call_graph_pagerank_tool(workspace_id: str, database_url: str | None = None) -> BaseTool:
    """Create a PageRank tool bound to a specific workspace."""

    @tool(args_schema=PageRankInput)
    def rank_call_graph_nodes(limit: int = 10) -> List[Dict[str, Any]]:
        """Return top-N call graph nodes ranked by PageRank score."""
        graph = get_graph(workspace_id, database_url)
        scores = _compute_pagerank(graph)
        if not scores:
            return []
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return [_format_node_entry(node_id, score, graph) for node_id, score in ordered[:limit]]

    return rank_call_graph_nodes


__all__ = ["PageRankInput", "build_call_graph_pagerank_tool"]
