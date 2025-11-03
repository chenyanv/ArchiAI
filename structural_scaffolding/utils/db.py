from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from structural_scaffolding.database import (
    ProfileRecord,
    WorkflowRecord,
    create_session,
)


def _ensure_session(
    session: Session | None,
    database_url: str | None,
) -> Tuple[Session, bool]:
    if session is not None:
        return session, False
    managed_session = create_session(database_url)
    return managed_session, True


def get_profile_calls(
    profile_id: str,
    *,
    session: Session | None = None,
    database_url: str | None = None,
) -> List[str]:
    """Return outbound call IDs for the given profile."""

    active_session, managed = _ensure_session(session, database_url)
    try:
        record = active_session.get(ProfileRecord, profile_id)
        if record is None:
            return []
        calls: Sequence[str] = record.calls or []
        return list(calls)
    finally:
        if managed:
            active_session.close()


def get_profiles_metadata(
    profile_ids: Iterable[str],
    *,
    session: Session | None = None,
    database_url: str | None = None,
) -> Dict[str, Dict[str, Optional[str]]]:
    """Fetch lightweight metadata for a collection of profiles."""

    ids = list(dict.fromkeys(id_ for id_ in profile_ids if id_))
    if not ids:
        return {}

    active_session, managed = _ensure_session(session, database_url)
    try:
        stmt = select(ProfileRecord).where(ProfileRecord.id.in_(ids))
        records = active_session.scalars(stmt).all()
        metadata: Dict[str, Dict[str, Optional[str]]] = {}
        for record in records:
            record_data = record.data if isinstance(record.data, dict) else {}
            display_name = (
                record.function_name
                or record.class_name
                or record_data.get("name")
                or record.id
            )
            metadata[record.id] = {
                "file_path": record.file_path,
                "name": display_name,
                "kind": record.kind,
            }
        return metadata
    finally:
        if managed:
            active_session.close()


def get_full_profiles(
    profile_ids: Iterable[str],
    *,
    session: Session | None = None,
    database_url: str | None = None,
) -> Dict[str, Dict[str, object]]:
    """Return full profile payloads required for workflow synthesis."""

    ids = list(dict.fromkeys(id_ for id_ in profile_ids if id_))
    if not ids:
        return {}

    active_session, managed = _ensure_session(session, database_url)
    try:
        stmt = select(ProfileRecord).where(ProfileRecord.id.in_(ids))
        records = active_session.scalars(stmt).all()
        payloads: Dict[str, Dict[str, object]] = {}
        for record in records:
            record_data = record.data if isinstance(record.data, dict) else {}
            summary_payload = None
            if isinstance(record_data, dict):
                raw_summary = record_data.get("summary")
                summary_payload = raw_summary if raw_summary is not None else record_data.get("summaries")
            payloads[record.id] = {
                "file_path": record.file_path,
                "name": record.function_name
                or record.class_name
                or record_data.get("name")
                or record.id,
                "source_code": record.source_code,
                "summary": summary_payload,
                "workflow_hints": _extract_workflow_hints(record_data),
                "data": record_data,
            }
        return payloads
    finally:
        if managed:
            active_session.close()


def save_workflow(
    entry_point_id: str,
    workflow_payload: Dict[str, object],
    *,
    session: Session | None = None,
    database_url: str | None = None,
) -> WorkflowRecord:
    """Persist workflow JSON for an entry point. Existing records are updated."""

    active_session, managed = _ensure_session(session, database_url)
    try:
        workflow_name = workflow_payload.get("workflow_name")
        if workflow_name is not None and not isinstance(workflow_name, str):
            workflow_name = str(workflow_name)

        record = (
            active_session.query(WorkflowRecord)
            .filter(WorkflowRecord.entry_point_id == entry_point_id)
            .first()
        )
        if record is None:
            record = WorkflowRecord(
                entry_point_id=entry_point_id,
                workflow_name=workflow_name,
                workflow=workflow_payload,
            )
        else:
            record.workflow = workflow_payload
            record.workflow_name = workflow_name

        active_session.add(record)
        active_session.commit()
        return record
    except Exception:
        active_session.rollback()
        raise
    finally:
        if managed:
            active_session.close()


def _extract_workflow_hints(record_data: dict | None) -> Optional[dict]:
    """Align hint extraction with entry point detection logic."""

    if not isinstance(record_data, dict):
        return None

    hints = record_data.get("workflow_hints")
    if isinstance(hints, dict):
        return hints

    summaries = record_data.get("summaries")
    if isinstance(summaries, dict):
        direct = summaries.get("workflow_hints")
        if isinstance(direct, dict):
            return direct
        level_1 = summaries.get("level_1")
        if isinstance(level_1, dict):
            nested = level_1.get("workflow_hints")
            if isinstance(nested, dict):
                return nested

    return None


__all__ = [
    "get_full_profiles",
    "get_profile_calls",
    "get_profiles_metadata",
    "save_workflow",
]
