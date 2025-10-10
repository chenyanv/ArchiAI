from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from sqlalchemy.orm import Session

from structural_scaffolding.database import ProfileRecord

from .models import CallGraphEdge, CallGraphNode, ConfidenceLevel


@dataclass(slots=True)
class CallGraphDiagnostics:
    root_path: str | None
    profile_count: int
    records_with_calls: int
    edge_count: int
    sample_callers: List[str]


class CallGraphBuilder:
    """Construct a static call graph from stored profile call metadata."""

    def __init__(
        self,
        session: Session,
        *,
        root_path: str | None = None,
    ) -> None:
        self._session = session
        self._root_path = root_path
        self._diagnostics: CallGraphDiagnostics | None = None

    def build(self) -> tuple[list[CallGraphNode], list[CallGraphEdge]]:
        records = self._load_profiles()
        alias_index = self._build_alias_index(records)
        nodes = [self._build_node(record) for record in records]
        edges = self._build_edges(records, alias_index)
        self._diagnostics = CallGraphDiagnostics(
            root_path=self._root_path,
            profile_count=len(records),
            records_with_calls=sum(1 for record in records if (record.calls or [])),
            edge_count=len(edges),
            sample_callers=[
                (record.file_path or "") for record in records if record.calls and (record.file_path or "")
            ][:5],
        )
        return nodes, edges

    def build_and_export(self, output_path: Path) -> tuple[list[CallGraphNode], list[CallGraphEdge]]:
        nodes, edges = self.build()
        self.export(nodes, edges, output_path)
        return nodes, edges

    def export(self, nodes: Iterable[CallGraphNode], edges: Iterable[CallGraphEdge], output_path: Path) -> None:
        node_list = [node.to_dict() for node in nodes]
        edge_list = [edge.to_dict() for edge in edges]
        payload = {
            "nodes": node_list,
            "edges": edge_list,
            "metadata": {
                "node_count": len(node_list),
                "edge_count": len(edge_list),
            },
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2))

    def _load_profiles(self) -> List[ProfileRecord]:
        query = self._session.query(ProfileRecord).filter(ProfileRecord.calls.isnot(None))
        if self._root_path:
            query = query.filter(ProfileRecord.root_path == self._root_path)
        return list(query.yield_per(500))

    def _build_alias_index(self, records: Sequence[ProfileRecord]) -> Dict[str, List[str]]:
        alias_map: Dict[str, List[str]] = defaultdict(list)
        for record in records:
            for alias in _aliases_for(record):
                normalised = _normalise_alias(alias)
                if not normalised:
                    continue
                if record.id not in alias_map[normalised]:
                    alias_map[normalised].append(record.id)
        return alias_map

    def _build_node(self, record: ProfileRecord) -> CallGraphNode:
        name = _derive_node_name(record)
        return CallGraphNode(
            profile_id=record.id,
            name=name,
            kind=record.kind,
            file_path=record.file_path or "",
        )

    def _build_edges(
        self,
        records: Sequence[ProfileRecord],
        alias_index: Dict[str, List[str]],
    ) -> List[CallGraphEdge]:
        edges: List[CallGraphEdge] = []
        seen: set[tuple[str, str, str | None]] = set()

        for record in records:
            calls = list(dict.fromkeys(record.calls or ()))
            if not calls:
                continue

            caller_id = record.id
            for target in calls:
                if not target:
                    continue
                target_text = str(target)
                match = self._resolve_call(target_text, alias_index)
                edge_key = (caller_id, target_text, match.resolved_profile_id)
                if edge_key in seen:
                    continue
                seen.add(edge_key)

                edges.append(
                    CallGraphEdge(
                        caller=caller_id,
                        target=target_text,
                        confidence=match.confidence,
                        resolved_profile_id=match.resolved_profile_id,
                        candidates=match.candidates,
                    )
                )

        edges.sort(
            key=lambda edge: (
                edge.caller,
                _confidence_rank(edge.confidence),
                edge.target,
            )
        )
        return edges

    def _resolve_call(self, target: str, alias_index: Dict[str, List[str]]) -> "_ResolutionResult":
        normalised = _normalise_call(target)
        if not normalised:
            return _ResolutionResult(target=target, confidence=ConfidenceLevel.UNKNOWN)

        candidates = alias_index.get(normalised, [])
        if candidates:
            if len(candidates) == 1:
                return _ResolutionResult(
                    target=target,
                    confidence=ConfidenceLevel.HIGH,
                    resolved_profile_id=candidates[0],
                    candidates=candidates,
                )
            return _ResolutionResult(
                target=target,
                confidence=ConfidenceLevel.MEDIUM,
                candidates=candidates,
            )

        # Fallback to matching on the final segment only.
        final_segment = normalised.split(".")[-1]
        if final_segment and final_segment != normalised:
            fallback_candidates = alias_index.get(final_segment, [])
            if fallback_candidates:
                confidence = ConfidenceLevel.MEDIUM if len(fallback_candidates) == 1 else ConfidenceLevel.LOW
                resolved = fallback_candidates[0] if len(fallback_candidates) == 1 else None
                return _ResolutionResult(
                    target=target,
                    confidence=confidence,
                    resolved_profile_id=resolved,
                    candidates=fallback_candidates,
                )

        return _ResolutionResult(target=target, confidence=ConfidenceLevel.UNKNOWN)

    @property
    def diagnostics(self) -> CallGraphDiagnostics | None:
        return self._diagnostics


@dataclass(slots=True)
class _ResolutionResult:
    target: str
    confidence: ConfidenceLevel
    resolved_profile_id: str | None = None
    candidates: List[str] | None = None

    def __post_init__(self) -> None:
        if self.candidates is None:
            self.candidates = []


def _aliases_for(record: ProfileRecord) -> List[str]:
    aliases: List[str] = []
    file_path = (record.file_path or "").replace("\\", "/")
    module_path = _module_path(file_path)

    if record.function_name:
        aliases.append(record.function_name)
    if record.class_name:
        aliases.append(record.class_name)
        if record.function_name:
            aliases.append(f"{record.class_name}.{record.function_name}")

    if module_path:
        if record.function_name:
            aliases.append(f"{module_path}.{record.function_name}")
        if record.class_name:
            aliases.append(f"{module_path}.{record.class_name}")
            if record.function_name:
                aliases.append(f"{module_path}.{record.class_name}.{record.function_name}")

    # Include profile identifier segments for disambiguation.
    tail = record.id.split("::", 1)[-1]
    aliases.append(tail)
    aliases.append(tail.replace("::", "."))

    return list(dict.fromkeys(alias for alias in aliases if alias))


def _derive_node_name(record: ProfileRecord) -> str:
    if record.class_name and record.function_name:
        return f"{record.class_name}.{record.function_name}"
    if record.function_name:
        return record.function_name
    if record.class_name:
        return record.class_name
    return record.id


def _module_path(file_path: str) -> str:
    if not file_path:
        return ""
    path = file_path.replace("\\", "/")
    if path.endswith(".py"):
        path = path[:-3]
    segments = [segment for segment in path.split("/") if segment and segment not in {".", ".."}]
    if segments and segments[-1] == "__init__":
        segments = segments[:-1]
    return ".".join(segment.replace("-", "_") for segment in segments)


def _normalise_alias(alias: str) -> str:
    return _normalise_call(alias)


def _normalise_call(target: str) -> str:
    cleaned = target.strip()
    if not cleaned:
        return ""
    # Remove trailing parentheses and whitespace.
    if cleaned.endswith("()"):
        cleaned = cleaned[:-2]
    if cleaned.startswith("super("):
        closing = cleaned.find(").")
        if closing != -1:
            cleaned = cleaned[closing + 2 :]
        else:
            closing = cleaned.find(")")
            if closing != -1:
                cleaned = cleaned[closing + 1 :]
    replacements = ("self.", "cls.", "super().")
    for prefix in replacements:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    cleaned = cleaned.replace("()", "")
    cleaned = cleaned.replace("[0]", "")
    cleaned = cleaned.replace("[1]", "")
    if cleaned.startswith("await"):
        cleaned = cleaned[len("await") :]
    if cleaned.startswith("return"):
        cleaned = cleaned[len("return") :]
    return cleaned.strip().strip(".").lower()


def _confidence_rank(confidence: ConfidenceLevel) -> int:
    order = {
        ConfidenceLevel.HIGH: 0,
        ConfidenceLevel.MEDIUM: 1,
        ConfidenceLevel.LOW: 2,
        ConfidenceLevel.UNKNOWN: 3,
    }
    return order.get(confidence, 4)


__all__ = ["CallGraphBuilder"]
