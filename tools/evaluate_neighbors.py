"""
LangGraph tool that surfaces candidate neighbours in the call graph.

Scores provide a confidence hint when the agent is unsure, but objectives and
domain knowledge must always drive the final decision.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import math
import networkx as nx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from .graph_cache import _load_cached_graph
from .graph_queries import DEFAULT_GRAPH_PATH
DEFAULT_SCORING_METHOD = "weighted_traffic"
SUPPORTED_SCORING_METHODS = {DEFAULT_SCORING_METHOD}


def _call_successors(graph: nx.MultiDiGraph, node_id: str) -> List[str]:
    neighbors: List[str] = []
    for neighbor in graph.successors(node_id):
        edge_data = graph.get_edge_data(node_id, neighbor)
        if not edge_data:
            continue
        if graph.is_multigraph():
            if any(attrs.get("type") == "CALLS" for attrs in edge_data.values()):
                neighbors.append(neighbor)
        else:
            if edge_data.get("type") == "CALLS":
                neighbors.append(neighbor)
    return neighbors


def _normalise_category(node_attrs: Dict[str, Any]) -> str:
    category = node_attrs.get("category") or node_attrs.get("kind")
    if isinstance(category, str) and category:
        return category
    return "unknown"


def _score_weighted_traffic(
    graph: nx.MultiDiGraph,
    neighbors: List[str],
) -> Dict[str, float]:
    """
    Rank neighbors by their weighted in-degree, which favors calls from
    higher-value categories and suppresses noisy utility traffic.
    """
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


def _compute_scores(
    graph: nx.MultiDiGraph,
    neighbors: List[str],
    scoring_method: str,
) -> Dict[str, float]:
    if scoring_method == "weighted_traffic":
        return _score_weighted_traffic(graph, neighbors)

    raise ValueError(
        f"Unsupported scoring_method '{scoring_method}'. "
        f"Supported options: {', '.join(sorted(SUPPORTED_SCORING_METHODS))}."
    )


class EvaluateNeighborsInput(BaseModel):
    node_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the call graph node whose downstream neighbors we want to inspect.",
    )
    scoring_method: str = Field(
        DEFAULT_SCORING_METHOD,
        description=(
            "Scoring strategy for ranking neighbors. Defaults to 'weighted_traffic', "
            "which sums incoming weighted calls."
        ),
    )


def _evaluate_neighbors(
    graph: nx.MultiDiGraph,
    node_id: str,
    scoring_method: str = DEFAULT_SCORING_METHOD,
) -> List[Dict[str, Any]]:
    if node_id not in graph:
        raise ValueError(f"Node '{node_id}' does not exist in the call graph.")

    neighbors = _call_successors(graph, node_id)
    if not neighbors:
        return []

    method = (scoring_method or DEFAULT_SCORING_METHOD).strip().lower()
    if method not in SUPPORTED_SCORING_METHODS:
        raise ValueError(
            f"Unsupported scoring_method '{scoring_method}'. "
            f"Supported options: {', '.join(sorted(SUPPORTED_SCORING_METHODS))}."
        )

    scores = _compute_scores(graph, neighbors, method)

    ranked_candidates = [
        neighbor for neighbor in neighbors if scores.get(neighbor, 0.0) > 0.0
    ]
    if not ranked_candidates:
        return []

    ranked = sorted(
        ranked_candidates,
        key=lambda neighbor: (scores.get(neighbor, 0.0), neighbor),
        reverse=True,
    )

    results: List[Dict[str, Any]] = []
    for neighbor in ranked:
        node_attrs = graph.nodes[neighbor]
        category = _normalise_category(node_attrs)
        results.append(
            {
                "id": neighbor,
                "score": scores.get(neighbor, 0.0),
                "category": category,
            }
        )
    return results


@tool(args_schema=EvaluateNeighborsInput)
def evaluate_neighbors(
    node_id: str,
    scoring_method: str = DEFAULT_SCORING_METHOD,
) -> List[Dict[str, Any]]:
    """Suggest downstream neighbors for a call graph node, ranked by the selected scoring method.

    The returned scores are advisory suggestions for sub-agents. They should combine
    these signals with domain knowledge (e.g. function names) before acting.
    When the next move is already dictated by the objective, the agent should
    follow that plan rather than the ranking. Scores are advisory signals, not directives.
    """
    graph = _load_cached_graph(str(DEFAULT_GRAPH_PATH))
    return _evaluate_neighbors(graph, node_id, scoring_method)


__all__ = [
    "EvaluateNeighborsInput",
    "evaluate_neighbors",
]
