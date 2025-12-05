"""LangGraph tool that surfaces candidate neighbours in the call graph.

Scores provide a confidence hint when the agent is unsure, but objectives and
domain knowledge must always drive the final decision.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

import networkx as nx
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from .graph_queries import get_graph, normalise_category

DEFAULT_SCORING_METHOD = "weighted_traffic"
SUPPORTED_SCORING_METHODS = {DEFAULT_SCORING_METHOD}


class EvaluateNeighborsInput(BaseModel):
    node_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the call graph node whose downstream neighbors we want to inspect.",
    )
    scoring_method: str = Field(
        DEFAULT_SCORING_METHOD,
        description="Scoring strategy for ranking neighbors. Defaults to 'weighted_traffic'.",
    )


def _call_successors(graph: nx.MultiDiGraph, node_id: str) -> List[str]:
    neighbors: List[str] = []
    for neighbor in graph.successors(node_id):
        edge_data = graph.get_edge_data(node_id, neighbor)
        if not edge_data:
            continue
        if graph.is_multigraph():
            if any(attrs.get("type") == "CALLS" for attrs in edge_data.values()):
                neighbors.append(neighbor)
        elif edge_data.get("type") == "CALLS":
            neighbors.append(neighbor)
    return neighbors


def _score_weighted_traffic(graph: nx.MultiDiGraph, neighbors: List[str]) -> Dict[str, float]:
    """Rank neighbors by weighted in-degree, favoring calls from higher-value categories."""
    scores: Dict[str, float] = {}
    for neighbor in neighbors:
        weighted_degree = graph.in_degree(neighbor, weight="weight")
        try:
            score = float(weighted_degree)
        except (TypeError, ValueError):
            score = 0.0
        if not math.isfinite(score) or score < 0.0:
            score = 0.0
        scores[neighbor] = score
    return scores


def _compute_scores(graph: nx.MultiDiGraph, neighbors: List[str], scoring_method: str) -> Dict[str, float]:
    if scoring_method == "weighted_traffic":
        return _score_weighted_traffic(graph, neighbors)
    raise ValueError(f"Unsupported scoring_method '{scoring_method}'. Supported: {', '.join(sorted(SUPPORTED_SCORING_METHODS))}.")


def _evaluate_neighbors_impl(
    node_id: str,
    workspace_id: str,
    database_url: str | None,
    scoring_method: str = DEFAULT_SCORING_METHOD,
) -> List[Dict[str, Any]]:
    """Core implementation for evaluate_neighbors."""
    graph = get_graph(workspace_id, database_url)
    if node_id not in graph:
        raise ValueError(f"Node '{node_id}' does not exist in the call graph.")

    neighbors = _call_successors(graph, node_id)
    if not neighbors:
        return []

    method = (scoring_method or DEFAULT_SCORING_METHOD).strip().lower()
    if method not in SUPPORTED_SCORING_METHODS:
        raise ValueError(f"Unsupported scoring_method '{scoring_method}'. Supported: {', '.join(sorted(SUPPORTED_SCORING_METHODS))}.")

    scores = _compute_scores(graph, neighbors, method)
    ranked = sorted(
        [n for n in neighbors if scores.get(n, 0.0) > 0.0],
        key=lambda n: (scores.get(n, 0.0), n),
        reverse=True,
    )

    return [{"id": neighbor, "score": scores.get(neighbor, 0.0), "category": normalise_category(graph.nodes[neighbor])} for neighbor in ranked]


def build_evaluate_neighbors_tool(workspace_id: str, database_url: str | None = None) -> BaseTool:
    """Create an evaluate_neighbors tool bound to a specific workspace."""

    @tool(args_schema=EvaluateNeighborsInput)
    def evaluate_neighbors(node_id: str, scoring_method: str = DEFAULT_SCORING_METHOD) -> List[Dict[str, Any]]:
        """Suggest downstream neighbors for a call graph node, ranked by the selected scoring method.

        The returned scores are advisory suggestions for sub-agents. They should combine
        these signals with domain knowledge before acting. Scores are advisory signals, not directives.
        """
        return _evaluate_neighbors_impl(node_id, workspace_id, database_url, scoring_method)

    return evaluate_neighbors


__all__ = ["EvaluateNeighborsInput", "build_evaluate_neighbors_tool"]
