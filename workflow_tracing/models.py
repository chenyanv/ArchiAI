from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class EntryPointCategory(str, Enum):
    WEB_API = "web_api"
    ASYNC_LISTENER = "async_listener"
    SCHEDULED_JOB = "scheduled_job"


@dataclass(slots=True)
class EntryPointCandidate:
    profile_id: str
    kind: str
    name: str
    file_path: str
    start_line: int
    category: EntryPointCategory
    detector: str
    confidence: ConfidenceLevel
    reasons: List[str] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    docstring: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "kind": self.kind,
            "name": self.name,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "category": self.category.value,
            "detector": self.detector,
            "confidence": self.confidence.value,
            "reasons": list(self.reasons),
            "decorators": list(self.decorators),
            "docstring": self.docstring,
        }


@dataclass(slots=True)
class CallGraphNode:
    profile_id: str
    name: str
    kind: str
    file_path: str

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "kind": self.kind,
            "file_path": self.file_path,
        }


@dataclass(slots=True)
class CallGraphEdge:
    caller: str
    target: str
    confidence: ConfidenceLevel
    resolved_profile_id: Optional[str] = None
    candidates: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = {
            "caller": self.caller,
            "target": self.target,
            "confidence": self.confidence.value,
        }
        if self.resolved_profile_id:
            payload["resolved_profile_id"] = self.resolved_profile_id
        if self.candidates:
            payload["candidates"] = list(self.candidates)
        return payload


@dataclass(slots=True)
class WorkflowStep:
    order: int
    profile_id: Optional[str]
    name: str
    kind: str
    file_path: Optional[str]
    summary: dict
    workflow_hints: dict
    docstring: Optional[str]
    outbound_calls: List[str]
    source: str
    confidence: ConfidenceLevel
    call_target: Optional[str] = None
    entry_point: Optional[dict] = None

    def to_dict(self) -> dict:
        payload = {
            "order": self.order,
            "profile_id": self.profile_id,
            "name": self.name,
            "kind": self.kind,
            "file_path": self.file_path,
            "summary": self.summary,
            "workflow_hints": self.workflow_hints,
            "docstring": self.docstring,
            "outbound_calls": list(self.outbound_calls),
            "source": self.source,
            "confidence": self.confidence.value,
        }
        if self.call_target:
            payload["call_target"] = self.call_target
        if self.entry_point is not None:
            payload["entry_point"] = self.entry_point
        return payload


@dataclass(slots=True)
class WorkflowScript:
    entry_point: EntryPointCandidate
    steps: List[WorkflowStep]
    synopsis: str
    call_chain: List[str]
    notes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "entry_point": self.entry_point.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "synopsis": self.synopsis,
            "call_chain": list(self.call_chain),
            "notes": dict(self.notes),
        }


__all__ = [
    "CallGraphEdge",
    "CallGraphNode",
    "ConfidenceLevel",
    "EntryPointCandidate",
    "EntryPointCategory",
    "WorkflowScript",
    "WorkflowStep",
]
