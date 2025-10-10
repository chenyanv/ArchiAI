from __future__ import annotations

from typing import Any, Dict

from .graph import build_orchestration_graph
from .state import AgentConfig, AgentState, DirectorySummary, TableSnapshot


def run_orchestration_agent(config: AgentConfig) -> Dict[str, Any]:
    """Convenience helper that builds and runs the orchestration LangGraph."""

    graph = build_orchestration_graph(config)
    initial_state: AgentState = {
        "config": config,
        "events": [],
        "errors": [],
    }
    return graph.invoke(initial_state)


__all__ = [
    "AgentConfig",
    "AgentState",
    "DirectorySummary",
    "TableSnapshot",
    "build_orchestration_graph",
    "run_orchestration_agent",
]
