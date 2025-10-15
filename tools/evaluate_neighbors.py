"""
LangGraph tool that surfaces candidate neighbours in the call graph.

Scores provide a confidence hint when the agent is unsure, but objectives and
domain knowledge must always drive the final decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping

import math
import networkx as nx
from pydantic import BaseModel, Field

from load_graph import load_graph_from_json

DEFAULT_GRAPH_PATH = Path("results/graphs/call_graph.json")
DEFAULT_SCORING_METHOD = "weighted_traffic"
SUPPORTED_SCORING_METHODS = {DEFAULT_SCORING_METHOD}


@lru_cache(maxsize=1)
def _load_cached_graph(path: str) -> nx.DiGraph:
    """Load and cache the call graph to avoid repeated disk I/O."""
    return load_graph_from_json(path)


def _normalise_category(node_attrs: Dict[str, Any]) -> str:
    category = node_attrs.get("category") or node_attrs.get("kind")
    if isinstance(category, str) and category:
        return category
    return "unknown"


def _score_weighted_traffic(
    graph: nx.DiGraph,
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
    graph: nx.DiGraph,
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


@dataclass(frozen=True)
class EvaluateNeighborsTool:
    """Expose advisory neighbour rankings; downstream choices remain objective-driven."""

    graph_path: Path
    name: str = "evaluate_neighbors"
    description: str = (
        "Suggest downstream neighbors for a call graph node, ranked by the selected "
        "scoring method. Scores are advisory signals, not directives."
    )
    args_schema = EvaluateNeighborsInput

    def __post_init__(self) -> None:
        resolved = self.graph_path.expanduser().resolve()
        object.__setattr__(self, "graph_path", resolved)

    def _run(
        self,
        node_id: str,
        scoring_method: str = DEFAULT_SCORING_METHOD,
    ) -> List[Dict[str, Any]]:
        graph = _load_cached_graph(str(self.graph_path))

        if node_id not in graph:
            raise ValueError(f"Node '{node_id}' does not exist in the call graph.")

        neighbors = list(graph.successors(node_id))
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

    def invoke(self, payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
        if isinstance(payload, EvaluateNeighborsInput):
            params = payload
        elif isinstance(payload, Mapping):
            params = self.args_schema(**payload)
        else:
            raise TypeError("Tool payload must be a mapping or EvaluateNeighborsInput.")
        return self._run(params.node_id, params.scoring_method)

    def __call__(self, payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
        return self.invoke(payload)


def build_evaluate_neighbors_tool(
    graph_path: Path | str = DEFAULT_GRAPH_PATH,
) -> EvaluateNeighborsTool:
    """
    Create a LangGraph-compatible tool that surfaces ranked downstream neighbors.

    The returned scores are advisory suggestions for sub-agents. They should combine
    these signals with domain knowledge (e.g. function names) before acting.
    When the next move is already dictated by the objective, the agent should
    follow that plan rather than the ranking.
    """
    return EvaluateNeighborsTool(Path(graph_path))


evaluate_neighbors_tool = build_evaluate_neighbors_tool()
