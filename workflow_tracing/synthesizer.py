from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set

from sqlalchemy.orm import Session

from .models import (
    CallGraphEdge,
    ConfidenceLevel,
    EntryPointCandidate,
    WorkflowScript,
    WorkflowStep,
)
from .repository import ProfileRepository


class WorkflowSynthesizer:
    """Compose workflow scripts by traversing the call graph from entry points."""

    def __init__(
        self,
        session: Session,
        *,
        orchestration_summary: str | None = None,
        max_depth: int = 6,
        max_steps: int = 20,
    ) -> None:
        self._profiles = ProfileRepository(session)
        self._orchestration_summary = orchestration_summary
        self._max_depth = max_depth
        self._max_steps = max_steps

    def synthesise(
        self,
        entry_points: Sequence[EntryPointCandidate],
        call_edges: Sequence[CallGraphEdge],
    ) -> List[WorkflowScript]:
        adjacency = self._build_adjacency(call_edges)
        scripts: List[WorkflowScript] = []

        for entry in entry_points:
            script = self._build_script(entry, adjacency)
            if script is not None:
                scripts.append(script)

        return scripts

    def synthesise_and_export(
        self,
        entry_points: Sequence[EntryPointCandidate],
        call_edges: Sequence[CallGraphEdge],
        output_path: Path,
    ) -> List[WorkflowScript]:
        scripts = self.synthesise(entry_points, call_edges)
        self.export(scripts, output_path)
        return scripts

    def export(self, scripts: Iterable[WorkflowScript], output_path: Path) -> None:
        script_list = list(scripts)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "workflow_count": len(script_list),
            "orchestration_summary": self._orchestration_summary,
            "workflows": [script.to_dict() for script in script_list],
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2))

    def _build_adjacency(self, call_edges: Sequence[CallGraphEdge]) -> Dict[str, List[CallGraphEdge]]:
        adjacency: Dict[str, List[CallGraphEdge]] = defaultdict(list)
        for edge in call_edges:
            adjacency[edge.caller].append(edge)

        for edges in adjacency.values():
            edges.sort(
                key=lambda edge: (
                    _confidence_rank(edge.confidence),
                    edge.target,
                )
            )
        return adjacency

    def _build_script(
        self,
        entry_point: EntryPointCandidate,
        adjacency: Dict[str, List[CallGraphEdge]],
    ) -> WorkflowScript | None:
        entry_record = self._profiles.get(entry_point.profile_id)
        if entry_record is None:
            return None

        steps: List[WorkflowStep] = []
        visited: Set[str] = set()

        self._expand_path(
            profile_id=entry_point.profile_id,
            adjacency=adjacency,
            steps=steps,
            visited=visited,
            depth=0,
            incoming_edge=None,
            entry_point=entry_point,
        )

        if not steps:
            return None

        call_chain = [step.profile_id for step in steps if step.profile_id]
        synopsis = _compose_synopsis(entry_point, steps)

        notes = {
            "category": entry_point.category.value,
            "detector": entry_point.detector,
            "confidence": entry_point.confidence.value,
            "reasons": entry_point.reasons,
        }
        if self._orchestration_summary:
            notes["orchestration_summary"] = self._orchestration_summary

        return WorkflowScript(
            entry_point=entry_point,
            steps=steps,
            synopsis=synopsis,
            call_chain=call_chain,
            notes=notes,
        )

    def _expand_path(
        self,
        profile_id: str,
        *,
        adjacency: Dict[str, List[CallGraphEdge]],
        steps: List[WorkflowStep],
        visited: Set[str],
        depth: int,
        incoming_edge: CallGraphEdge | None,
        entry_point: EntryPointCandidate | None,
    ) -> None:
        if depth > self._max_depth or len(steps) >= self._max_steps:
            return

        record = self._profiles.get(profile_id)
        if record is None:
            return

        step = _build_step_from_record(
            order=len(steps),
            record=record,
            confidence=entry_point.confidence if depth == 0 else (incoming_edge.confidence if incoming_edge else ConfidenceLevel.UNKNOWN),
            source="entry_point" if depth == 0 else "call_edge",
            incoming_edge=incoming_edge,
            entry_point=entry_point if depth == 0 else None,
        )
        steps.append(step)
        visited.add(profile_id)

        if depth == self._max_depth:
            return

        for edge in adjacency.get(profile_id, []):
            if len(steps) >= self._max_steps:
                break

            if edge.resolved_profile_id:
                if edge.resolved_profile_id in visited:
                    continue
                self._expand_path(
                    edge.resolved_profile_id,
                    adjacency=adjacency,
                    steps=steps,
                    visited=visited,
                    depth=depth + 1,
                    incoming_edge=edge,
                    entry_point=None,
                )
            else:
                steps.append(
                    _build_external_step(
                        order=len(steps),
                        edge=edge,
                    )
                )


def _build_step_from_record(
    *,
    order: int,
    record,
    confidence: ConfidenceLevel,
    source: str,
    incoming_edge: CallGraphEdge | None,
    entry_point: EntryPointCandidate | None,
) -> WorkflowStep:
    summaries = record.summaries if isinstance(record.summaries, dict) else {}
    level_1 = summaries.get("level_1")
    if not isinstance(level_1, dict):
        level_1 = {}

    summary_section = level_1.get("summary") if isinstance(level_1.get("summary"), dict) else {}
    workflow_hints = level_1.get("workflow_hints") if isinstance(level_1.get("workflow_hints"), dict) else {}

    docstring = record.docstring.strip() if isinstance(record.docstring, str) and record.docstring else None
    outbound_calls = list(dict.fromkeys(record.calls or []))[:8]

    entry_metadata = None
    if entry_point is not None:
        entry_metadata = {
            "category": entry_point.category.value,
            "detector": entry_point.detector,
            "confidence": entry_point.confidence.value,
            "reasons": entry_point.reasons,
        }

    return WorkflowStep(
        order=order,
        profile_id=record.id,
        name=_derive_display_name(record),
        kind=record.kind,
        file_path=record.file_path,
        summary=summary_section or {},
        workflow_hints=workflow_hints or {},
        docstring=docstring,
        outbound_calls=outbound_calls,
        source=source,
        confidence=confidence,
        call_target=incoming_edge.target if incoming_edge else None,
        entry_point=entry_metadata,
    )


def _build_external_step(*, order: int, edge: CallGraphEdge) -> WorkflowStep:
    return WorkflowStep(
        order=order,
        profile_id=None,
        name=edge.target,
        kind="external_call",
        file_path=None,
        summary={},
        workflow_hints={},
        docstring=None,
        outbound_calls=[],
        source="call_edge",
        confidence=edge.confidence,
        call_target=edge.target,
        entry_point=None,
    )


def _derive_display_name(record) -> str:
    if record.class_name and record.function_name:
        return f"{record.class_name}.{record.function_name}"
    if record.function_name:
        return record.function_name
    if record.class_name:
        return record.class_name
    return record.id


def _compose_synopsis(entry_point: EntryPointCandidate, steps: Sequence[WorkflowStep]) -> str:
    lines: List[str] = []
    lines.append(
        f"Entry `{entry_point.name}` ({entry_point.category.value}, confidence {entry_point.confidence.value})"
    )

    for step in steps:
        description = ""
        if step.summary:
            core = step.summary.get("core_identity") or step.summary.get("business_intent")
            if isinstance(core, str) and core:
                description = core
        if not description and step.docstring:
            description = step.docstring.strip().splitlines()[0]
        if not description:
            description = "No summary available."

        role = step.workflow_hints.get("role") if isinstance(step.workflow_hints, dict) else None
        qualifier = f" [{role}]" if role else ""

        if step.call_target and step.profile_id != entry_point.profile_id:
            lines.append(f"{step.order + 1}. {step.name}{qualifier} via `{step.call_target}` → {description}")
        else:
            lines.append(f"{step.order + 1}. {step.name}{qualifier} → {description}")

    return "\n".join(lines)


def _confidence_rank(confidence: ConfidenceLevel) -> int:
    order = {
        ConfidenceLevel.HIGH: 0,
        ConfidenceLevel.MEDIUM: 1,
        ConfidenceLevel.LOW: 2,
        ConfidenceLevel.UNKNOWN: 3,
    }
    return order.get(confidence, 4)


__all__ = ["WorkflowSynthesizer"]
