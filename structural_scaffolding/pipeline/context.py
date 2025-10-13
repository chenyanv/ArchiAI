from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from structural_scaffolding.database import ProfileRecord

from .data_access import load_profile, load_profiles_by_ids

_MAX_SOURCE_CHARS = 6000


@dataclass(slots=True)
class L1SummaryContext:
    profile_id: str
    kind: str
    display_name: str
    file_path: str
    docstring: str | None
    source_code: str
    public_members: List[str]
    outbound_calls: List[str]
    imports: List[str]
    related_profiles: List["RelatedProfileSnippet"]
    entry_point_candidates: List["EntryPointCandidateSnippet"]


@dataclass(slots=True)
class RelatedProfileSnippet:
    profile_id: str
    kind: str
    name: str
    file_path: str
    docstring: str | None
    source_code: str


@dataclass(slots=True)
class EntryPointCandidateSnippet:
    profile_id: str
    kind: str
    name: str
    docstring: str | None
    call_count: int
    outbound_calls: List[str]
    is_public: bool


@dataclass(slots=True)
class DirectoryFileSummary:
    file_path: str
    summary: dict
    workflow_hints: dict
    entry_point: Optional[dict]


@dataclass(slots=True)
class DirectoryChildSummary:
    directory_path: str
    level: int
    file_count: int
    summary: dict
    source_files: List[str]


@dataclass(slots=True)
class DirectorySummaryContext:
    root_path: str
    directory_path: str
    level: int
    files: List[DirectoryFileSummary]
    child_directories: List[DirectoryChildSummary]


def build_l1_context(session: Session, profile: ProfileRecord) -> L1SummaryContext:
    if profile.kind not in {"file", "class"}:
        raise ValueError(f"L1 context currently supports file/class profiles, got '{profile.kind}'")

    public_members = _collect_public_members(session, profile)
    outbound_calls = _unique_sequence(profile.calls or [])
    imports = _extract_imports(profile.source_code)
    source_code = _truncate_source(profile.source_code)
    # NOTE: We no longer pull related profile snippets for L1 summaries to keep the
    # prompt compact. The previous recursive lookup remains documented below for
    # potential future use.
    related_profiles: List[RelatedProfileSnippet] = []
    # related_profiles = _collect_related_profiles(session, profile, depth=1)

    display_name = _derive_display_name(profile)
    entry_point_candidates = _collect_entry_point_candidates(session, profile)

    return L1SummaryContext(
        profile_id=profile.id,
        kind=profile.kind,
        display_name=display_name,
        file_path=profile.file_path,
        docstring=profile.docstring,
        source_code=source_code,
        public_members=public_members,
        outbound_calls=outbound_calls,
        imports=imports,
        related_profiles=related_profiles,
        entry_point_candidates=entry_point_candidates,
    )


def _derive_display_name(profile: ProfileRecord) -> str:
    if profile.kind == "file":
        return profile.file_path
    if profile.class_name:
        return profile.class_name
    return profile.id


def _collect_public_members(session: Session, profile: ProfileRecord) -> List[str]:
    child_ids: Iterable[str] = profile.children or []
    if not child_ids:
        return []

    members: List[str] = []
    for child in load_profiles_by_ids(session, child_ids):
        name = child.function_name or child.class_name
        if not name:
            continue
        if child.kind in {"method", "function"} and name.startswith("_"):
            continue
        members.append(name)
    return _unique_sequence(members)


def _collect_related_profiles(
    session: Session,
    profile: ProfileRecord,
    *,
    depth: int,
) -> List[RelatedProfileSnippet]:
    if depth <= 0:
        return []

    visited = {profile.id}
    queue: List[tuple[str, int]] = []

    if profile.parent_id:
        queue.append((profile.parent_id, 1))

    for child_id in profile.children or []:
        queue.append((child_id, 1))

    snippets: List[RelatedProfileSnippet] = []

    while queue:
        target_id, level = queue.pop(0)
        if level > depth or target_id in visited:
            continue
        visited.add(target_id)

        related = load_profile(session, target_id)
        if related is None:
            continue

        snippets.append(
            RelatedProfileSnippet(
                profile_id=related.id,
                kind=related.kind,
                name=_derive_display_name(related),
                file_path=related.file_path,
                docstring=related.docstring,
                source_code=_truncate_source(related.source_code),
            )
        )

    return snippets


def _collect_entry_point_candidates(session: Session, profile: ProfileRecord) -> List[EntryPointCandidateSnippet]:
    child_ids: Iterable[str] = profile.children or []
    if not child_ids:
        return []

    exclusion_set = {
        "__init__",
        "__call__",
        "__repr__",
        "__str__",
        "__iter__",
        "__next__",
        "__enter__",
        "__exit__",
        "__getattr__",
        "__setattr__",
        "__del__",
        "__delitem__",
        "__getattribute__",
        "to_dict",
        "from_dict",
        "as_dict",
        "dict",
        "serialize",
        "deserialize",
    }

    snippets: List[EntryPointCandidateSnippet] = []
    for child in load_profiles_by_ids(session, child_ids):
        if child.kind not in {"function", "method"}:
            continue

        name = child.function_name or child.class_name or child.id
        normalised_name = name.lower() if isinstance(name, str) else ""
        base_name = normalised_name.rsplit(".", 1)[-1]
        if base_name in exclusion_set:
            continue

        doc = child.docstring
        calls = _unique_sequence(child.calls or [])
        snippets.append(
            EntryPointCandidateSnippet(
                profile_id=child.id,
                kind=child.kind,
                name=name,
                docstring=doc,
                call_count=len(calls),
                outbound_calls=calls[:8],
                is_public=bool(name and not name.startswith("_")),
            )
        )

    return snippets


def build_directory_context(
    session: Session,
    directory_path: str,
    *,
    root_path: Optional[str] = None,
) -> DirectorySummaryContext:
    target_directory = _normalise_directory_path(directory_path)
    target_level = _directory_level(target_directory)

    stmt = session.query(ProfileRecord).filter(ProfileRecord.kind == "file")
    if root_path is not None:
        stmt = stmt.filter(ProfileRecord.root_path == root_path)

    files: List[DirectoryFileSummary] = []
    resolved_root: Optional[str] = root_path

    for record in stmt:
        file_path = (record.file_path or "").replace("\\", "/")
        if not file_path:
            continue
        if _parent_directory(file_path) != target_directory:
            continue

        summaries = record.summaries if isinstance(record.summaries, dict) else {}
        level_1 = summaries.get("level_1")
        if not isinstance(level_1, dict):
            continue

        summary_section = level_1.get("summary")
        if not isinstance(summary_section, dict):
            summary_section = {}
        workflow_hints = level_1.get("workflow_hints")
        if not isinstance(workflow_hints, dict):
            workflow_hints = {}
        entry_point = level_1.get("entry_point")
        if not isinstance(entry_point, dict):
            entry_point = None

        files.append(
            DirectoryFileSummary(
                file_path=file_path,
                summary=summary_section,
                workflow_hints=workflow_hints,
                entry_point=entry_point,
            )
        )

        if resolved_root is None:
            resolved_root = record.root_path

    # Eagerly load child directory summaries so higher-level folders can build on
    # previously generated context.
    from structural_scaffolding.database import DirectorySummaryRecord  # local import to avoid cycles

    child_query = session.query(DirectorySummaryRecord)
    if root_path is not None:
        child_query = child_query.filter(DirectorySummaryRecord.root_path == root_path)

    child_directories: List[DirectoryChildSummary] = []
    for record in child_query:
        if resolved_root is not None and record.root_path != resolved_root:
            continue
        directory = _normalise_directory_path(record.directory_path or "")
        if directory == target_directory:
            continue
        if not _is_direct_child(directory, target_directory):
            continue
        if resolved_root is None:
            resolved_root = record.root_path
        child_directories.append(
            DirectoryChildSummary(
                directory_path=directory,
                level=_directory_level(directory),
                file_count=int(record.file_count or 0),
                summary=record.summary if isinstance(record.summary, dict) else {},
                source_files=list(record.source_files or []),
            )
        )

    if not files and not child_directories:
        raise ValueError(f"No context found for directory '{directory_path}'")

    return DirectorySummaryContext(
        root_path=resolved_root or "",
        directory_path=target_directory,
        level=target_level,
        files=files,
        child_directories=sorted(child_directories, key=lambda item: item.directory_path),
    )


def _extract_imports(source_code: str) -> List[str]:
    if not source_code:
        return []

    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    imports: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                target = f"{module}.{alias.name}" if module else alias.name
                imports.append(target)

    return _unique_sequence(imports)


def _truncate_source(source_code: str) -> str:
    if len(source_code) <= _MAX_SOURCE_CHARS:
        return source_code
    head = source_code[: _MAX_SOURCE_CHARS - 500]
    tail = source_code[-500:]
    return f"{head}\n...\n{tail}"


def _unique_sequence(items: Iterable[str]) -> List[str]:
    seen = dict.fromkeys(item for item in items if item)
    return list(seen)


def _normalise_directory_path(directory_path: str) -> str:
    if directory_path is None:
        return "."
    text = directory_path.strip()
    if not text or text in {".", "./"}:
        return "."
    normalised = text.strip("/").replace("\\", "/")
    return normalised or "."


def _split_directory_path(directory_path: str) -> List[str]:
    if not directory_path or directory_path in {".", "./"}:
        return []
    return [segment for segment in directory_path.strip("/").split("/") if segment and segment != "."]


def _directory_level(directory_path: str) -> int:
    return len(_split_directory_path(directory_path))


def _parent_directory(path: str) -> str:
    segments = _split_directory_path(path)
    if not segments:
        return "."
    parent_segments = segments[:-1]
    if not parent_segments:
        return "."
    return "/".join(parent_segments)


def _is_direct_child(child: str, parent: str) -> bool:
    return _parent_directory(child) == parent


__all__ = [
    "DirectoryFileSummary",
    "DirectoryChildSummary",
    "DirectorySummaryContext",
    "EntryPointCandidateSnippet",
    "L1SummaryContext",
    "RelatedProfileSnippet",
    "build_directory_context",
    "build_l1_context",
]
