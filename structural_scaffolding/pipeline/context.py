from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Iterable, List

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


@dataclass(slots=True)
class RelatedProfileSnippet:
    profile_id: str
    kind: str
    name: str
    file_path: str
    docstring: str | None
    source_code: str


def build_l1_context(session: Session, profile: ProfileRecord) -> L1SummaryContext:
    if profile.kind not in {"file", "class"}:
        raise ValueError(f"L1 context currently supports file/class profiles, got '{profile.kind}'")

    public_members = _collect_public_members(session, profile)
    outbound_calls = _unique_sequence(profile.calls or [])
    imports = _extract_imports(profile.source_code)
    source_code = _truncate_source(profile.source_code)
    related_profiles = _collect_related_profiles(session, profile, depth=1)

    display_name = _derive_display_name(profile)

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


__all__ = ["L1SummaryContext", "RelatedProfileSnippet", "build_l1_context"]
