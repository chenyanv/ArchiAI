from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
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


@dataclass(slots=True)
class DirectoryInsight:
    root_path: str
    directory_path: str
    summary: dict
    file_count: int
    source_files: List[str] = field(default_factory=list)
    overview: Optional[str] = None
    key_capabilities: List[str] = field(default_factory=list)
    stage: Optional[str] = None
    stage_reason: Optional[str] = None
    matched_keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = {
            "root_path": self.root_path,
            "directory_path": self.directory_path,
            "summary": dict(self.summary),
            "file_count": self.file_count,
            "source_files": list(self.source_files),
            "overview": self.overview,
            "key_capabilities": list(self.key_capabilities),
            "stage": self.stage,
            "stage_reason": self.stage_reason,
        }
        if self.matched_keywords:
            payload["matched_keywords"] = list(self.matched_keywords)
        return payload


@dataclass(slots=True)
class ProfileInsight:
    profile_id: str
    name: str
    kind: str
    file_path: str
    directory_path: str
    summary: dict
    workflow_hints: dict
    docstring: Optional[str]
    core_identity: Optional[str]
    business_intent: Optional[str]
    workflow_role: Optional[str]
    stage: Optional[str] = None

    def to_dict(self) -> dict:
        payload = {
            "profile_id": self.profile_id,
            "name": self.name,
            "kind": self.kind,
            "file_path": self.file_path,
            "directory_path": self.directory_path,
            "summary": dict(self.summary),
            "workflow_hints": dict(self.workflow_hints),
            "docstring": self.docstring,
            "core_identity": self.core_identity,
            "business_intent": self.business_intent,
            "workflow_role": self.workflow_role,
            "stage": self.stage,
        }
        return payload


@dataclass(slots=True)
class TraceStage:
    key: str
    name: str
    goal: str
    directories: List[DirectoryInsight] = field(default_factory=list)
    highlighted_profiles: List[ProfileInsight] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "goal": self.goal,
            "directories": [directory.to_dict() for directory in self.directories],
            "highlighted_profiles": [profile.to_dict() for profile in self.highlighted_profiles],
        }


@dataclass(slots=True)
class TraceNarrative:
    title: str
    text: str
    orchestration_summary: Optional[str]
    stages: List[TraceStage]
    supporting_directories: List[DirectoryInsight] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "text": self.text,
            "orchestration_summary": self.orchestration_summary,
            "generated_at": self.generated_at.isoformat(),
            "stages": [stage.to_dict() for stage in self.stages],
            "supporting_directories": [directory.to_dict() for directory in self.supporting_directories],
            "notes": list(self.notes),
        }


__all__ = [
    "CallGraphEdge",
    "CallGraphNode",
    "ConfidenceLevel",
    "EntryPointCandidate",
    "EntryPointCategory",
    "DirectoryInsight",
    "ProfileInsight",
    "TraceNarrative",
    "TraceStage",
    "WorkflowScript",
    "WorkflowStep",
]
