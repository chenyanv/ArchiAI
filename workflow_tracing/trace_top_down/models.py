from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass(slots=True)
class PlannerComponent:
    """LLM-generated representation of a top-level business capability."""

    name: str
    description: str
    keywords: List[str] = field(default_factory=list)
    trace_tokens: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "keywords": list(self.keywords),
            "trace_tokens": list(self.trace_tokens),
            "evidence": list(self.evidence),
        }


@dataclass(slots=True)
class PlannerOutput:
    """Aggregated result for the top-level planning step."""

    summary: str
    components: List[PlannerComponent]
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "components": [component.to_dict() for component in self.components],
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class TraceSeed:
    """Pointer that can be used to resume tracing in subsequent steps."""

    token: str
    kind: str
    label: str
    description: Optional[str] = None
    profile_id: Optional[str] = None
    directory_path: Optional[str] = None
    file_path: Optional[str] = None
    docstring: Optional[str] = None
    summary: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "token": self.token,
            "kind": self.kind,
            "label": self.label,
            "description": self.description,
            "profile_id": self.profile_id,
            "directory_path": self.directory_path,
            "file_path": self.file_path,
            "docstring": self.docstring,
            "summary": self.summary,
            "aliases": list(self.aliases),
            "metadata": dict(self.metadata),
        }
        # Remove keys with None to keep output tidy.
        return {key: value for key, value in payload.items() if value not in (None, [], {})}


@dataclass(slots=True)
class ComponentOption:
    """Actionable option surfaced during component exploration."""

    title: str
    rationale: str
    workflow: str
    trace_tokens: List[str] = field(default_factory=list)
    considerations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "rationale": self.rationale,
            "workflow": self.workflow,
            "trace_tokens": list(self.trace_tokens),
            "considerations": list(self.considerations),
        }


@dataclass(slots=True)
class ComponentExploration:
    """LLM-backed exploration result for a user-selected component."""

    query: str
    analysis: str
    options: List[ComponentOption] = field(default_factory=list)
    trace_seeds: List[TraceSeed] = field(default_factory=list)
    source_tokens: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "analysis": self.analysis,
            "options": [option.to_dict() for option in self.options],
            "trace_seeds": [seed.to_dict() for seed in self.trace_seeds],
            "source_tokens": list(self.source_tokens),
        }


@dataclass(slots=True)
class ExplorationHistoryItem:
    """Historical record of a single interaction inside the top-down explorer."""

    timestamp: datetime
    exploration: ComponentExploration

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "exploration": self.exploration.to_dict(),
        }


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


__all__ = [
    "ComponentExploration",
    "ComponentOption",
    "ExplorationHistoryItem",
    "PlannerComponent",
    "PlannerOutput",
    "TraceSeed",
    "now_utc",
]

