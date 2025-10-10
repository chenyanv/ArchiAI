from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, TypedDict

from workflow_tracing.models import DirectoryInsight, ProfileInsight

from .models import (
    ExplorationHistoryItem,
    PlannerOutput,
    TraceSeed,
)


@dataclass(frozen=True, slots=True)
class TopDownAgentConfig:
    """Runtime configuration for the top-down tracing agent."""

    database_url: Optional[str] = None
    root_path: Optional[str] = None
    summary_path: Path = Path("results/orchestration.json")
    output_path: Path = Path("results/trace_top_down.md")
    json_path: Path = Path("results/trace_top_down.json")
    max_directories: int = 8
    profiles_per_directory: int = 6
    component_limit: int = 6
    enable_planner_llm: bool = True
    planner_model: Optional[str] = None
    planner_system_prompt: Optional[str] = None
    enable_analysis_llm: bool = True
    analysis_model: Optional[str] = None
    analysis_system_prompt: Optional[str] = None
    verbose: bool = False
    interactive_enabled: bool = True


class TopDownAgentState(TypedDict, total=False):
    config: TopDownAgentConfig
    events: List[str]
    errors: List[str]
    orchestration_summary: Optional[str]
    directory_hints: List[str]
    directory_insights: List[DirectoryInsight]
    profile_insights: List[ProfileInsight]
    planner_output: PlannerOutput
    trace_registry: "TraceRegistry"
    history: List[ExplorationHistoryItem]


class TraceRegistry:
    """Mutable registry of trace seeds exposed to the user."""

    def __init__(self) -> None:
        self._seeds: Dict[str, TraceSeed] = {}
        self._aliases: Dict[str, str] = {}
        self._ordered: List[str] = []

    def __contains__(self, token: str) -> bool:
        return self._normalise(token) in self._aliases or token in self._seeds

    def __len__(self) -> int:
        return len(self._seeds)

    def add(self, seed: TraceSeed) -> None:
        token = seed.token
        if token not in self._seeds:
            self._ordered.append(token)
        self._seeds[token] = seed
        aliases = set(seed.aliases or [])
        aliases.add(token)
        aliases.add(seed.label)
        if seed.file_path:
            aliases.add(seed.file_path)
        if seed.directory_path:
            aliases.add(seed.directory_path)
        if seed.profile_id:
            aliases.add(seed.profile_id)

        for alias in aliases:
            self._register_alias(token, alias)

    def extend(self, seeds: Iterable[TraceSeed]) -> None:
        for seed in seeds:
            self.add(seed)

    def get(self, token: str) -> TraceSeed | None:
        if token in self._seeds:
            return self._seeds[token]
        alias = self._aliases.get(self._normalise(token))
        if alias:
            return self._seeds.get(alias)
        return None

    def search(self, query: str) -> List[TraceSeed]:
        norm = self._normalise(query)
        if not norm:
            return []

        direct = self._aliases.get(norm)
        if direct:
            seed = self._seeds.get(direct)
            return [seed] if seed else []

        words = [word for word in norm.split() if word]
        if not words:
            return []

        matches: List[TraceSeed] = []
        for seed in self._seeds.values():
            haystack = " ".join(
                filter(
                    None,
                    [
                        seed.token,
                        seed.label,
                        seed.description,
                        seed.profile_id,
                        seed.file_path,
                        seed.directory_path,
                        " ".join(seed.aliases),
                    ],
                )
            )
            haystack_norm = self._normalise(haystack)
            if all(word in haystack_norm for word in words):
                matches.append(seed)
        return matches

    def all(self) -> List[TraceSeed]:
        return [self._seeds[token] for token in self._ordered if token in self._seeds]

    def tokens(self) -> List[str]:
        return [seed.token for seed in self.all()]

    def snapshot(self) -> List[dict]:
        return [seed.to_dict() for seed in self.all()]

    def _register_alias(self, token: str, alias: Optional[str]) -> None:
        normalised = self._normalise(alias)
        if not normalised:
            return
        self._aliases[normalised] = token

    @staticmethod
    def _normalise(value: Optional[str]) -> str:
        if value is None:
            return ""
        return " ".join(value.strip().lower().split())


def append_event(state: TopDownAgentState, message: str) -> TopDownAgentState:
    events = list(state.get("events", []))
    events.append(message)
    return {"events": events}


def append_error(state: TopDownAgentState, message: str) -> TopDownAgentState:
    errors = list(state.get("errors", []))
    errors.append(message)
    return {"errors": errors}


def extend_events(state: TopDownAgentState, messages: Sequence[str]) -> TopDownAgentState:
    events = list(state.get("events", []))
    events.extend(messages)
    return {"events": events}


__all__ = [
    "TopDownAgentConfig",
    "TopDownAgentState",
    "TraceRegistry",
    "append_error",
    "append_event",
    "extend_events",
]
