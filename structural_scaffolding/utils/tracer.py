from __future__ import annotations

import re
from typing import Iterable, List, Set

from sqlalchemy.orm import Session

from structural_scaffolding.database import create_session
from structural_scaffolding.utils import db as db_utils

# --- Tracer configuration defaults ---
DEFAULT_MAX_DEPTH = 5
FILTER_OUT_PATHS = ("/utils/", "/helpers/", "/common/")
FILTER_OUT_NAMES_REGEX = (r"^_", r"log_.*", r".*_validator$")

_FILTER_NAME_PATTERNS = tuple(re.compile(pattern) for pattern in FILTER_OUT_NAMES_REGEX)


def trace_workflow(
    start_profile_id: str,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    session: Session | None = None,
    database_url: str | None = None,
) -> List[str]:
    """Trace a workflow call chain starting from an entry profile."""

    if not start_profile_id:
        return []

    active_session = session or create_session(database_url)
    managed_session = session is None

    try:
        visited: Set[str] = set()
        raw_chain: List[str] = []

        _dfs_trace(
            start_profile_id,
            depth=0,
            max_depth=max_depth,
            visited=visited,
            chain=raw_chain,
            session=active_session,
        )

        clean_chain = _filter_chain(raw_chain, session=active_session)

        if raw_chain and raw_chain[0] not in clean_chain:
            clean_chain.insert(0, raw_chain[0])

        return clean_chain
    finally:
        if managed_session:
            active_session.close()


def _dfs_trace(
    current_id: str,
    *,
    depth: int,
    max_depth: int,
    visited: Set[str],
    chain: List[str],
    session: Session,
) -> None:
    """Recursive depth-first traversal of outbound profile calls."""

    if depth >= max_depth or current_id in visited:
        return

    visited.add(current_id)
    chain.append(current_id)

    calls = db_utils.get_profile_calls(current_id, session=session)
    for called_id in calls:
        if called_id:
            _dfs_trace(
                called_id,
                depth=depth + 1,
                max_depth=max_depth,
                visited=visited,
                chain=chain,
                session=session,
            )


def _filter_chain(raw_chain: Iterable[str], *, session: Session) -> List[str]:
    """Apply metadata-driven filters to reduce workflow noise."""

    raw_list = [profile_id for profile_id in raw_chain if profile_id]
    if not raw_list:
        return []

    metadata = db_utils.get_profiles_metadata(raw_list, session=session)
    clean_chain: List[str] = []

    for profile_id in raw_list:
        meta = metadata.get(profile_id)
        if not meta:
            continue

        file_path = meta.get("file_path") or ""
        if any(segment in file_path for segment in FILTER_OUT_PATHS):
            continue

        name = meta.get("name") or ""
        if any(pattern.match(name) for pattern in _FILTER_NAME_PATTERNS):
            continue

        clean_chain.append(profile_id)

    return clean_chain


__all__ = [
    "DEFAULT_MAX_DEPTH",
    "FILTER_OUT_NAMES_REGEX",
    "FILTER_OUT_PATHS",
    "trace_workflow",
]
