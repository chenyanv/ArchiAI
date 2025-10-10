from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, TypedDict

from .models import DirectoryInsight, ProfileInsight, TraceNarrative


@dataclass(frozen=True, slots=True)
class WorkflowAgentConfig:
    database_url: Optional[str] = None
    root_path: Optional[str] = None
    max_directories: int = 6
    profiles_per_directory: int = 4
    trace_output_path: Path = Path("results/workflow_trace.md")
    trace_json_path: Path = Path("results/workflow_trace.json")
    orchestration_summary: Optional[str] = None
    verbose: bool = False
    enable_llm_narrative: bool = False
    narrative_model: Optional[str] = None
    narrative_system_prompt: Optional[str] = None


class WorkflowAgentState(TypedDict, total=False):
    config: WorkflowAgentConfig
    events: List[str]
    errors: List[str]
    orchestration_summary: Optional[str]
    directory_hints: List[str]
    directory_insights: List[DirectoryInsight]
    profile_insights: List[ProfileInsight]
    trace_narrative: TraceNarrative


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
