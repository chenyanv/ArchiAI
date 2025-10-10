from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, TypedDict

from .models import (
    CallGraphEdge,
    CallGraphNode,
    EntryPointCandidate,
    WorkflowScript,
)


@dataclass(frozen=True, slots=True)
class WorkflowAgentConfig:
    database_url: Optional[str] = None
    root_path: Optional[str] = None
    include_tests: bool = False
    max_depth: int = 6
    max_steps: int = 20
    entry_points_path: Path = Path("results/entry_points.json")
    call_graph_path: Path = Path("results/call_graph.json")
    workflow_scripts_path: Path = Path("results/workflow_scripts.json")
    orchestration_summary: Optional[str] = None


class WorkflowAgentState(TypedDict, total=False):
    config: WorkflowAgentConfig
    events: List[str]
    errors: List[str]
    entry_points: List[EntryPointCandidate]
    call_graph_nodes: List[CallGraphNode]
    call_graph_edges: List[CallGraphEdge]
    workflows: List[WorkflowScript]


def append_event(state: WorkflowAgentState, message: str) -> WorkflowAgentState:
    events = list(state.get("events", []))
    events.append(message)
    return {"events": events}


def append_error(state: WorkflowAgentState, message: str) -> WorkflowAgentState:
    errors = list(state.get("errors", []))
    errors.append(message)
    return {"errors": errors}


def extend_events(state: WorkflowAgentState, messages: Sequence[str]) -> WorkflowAgentState:
    events = list(state.get("events", []))
    events.extend(messages)
    return {"events": events}


__all__ = [
    "WorkflowAgentConfig",
    "WorkflowAgentState",
    "append_error",
    "append_event",
    "extend_events",
]
