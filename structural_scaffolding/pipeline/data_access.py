from __future__ import annotations

from typing import Iterable, Sequence

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from structural_scaffolding.database import ProfileRecord
from structural_scaffolding.models import SummaryLevel


def _base_pending_query(kinds: Sequence[str]) -> Select[tuple[ProfileRecord]]:
    return (
        select(ProfileRecord)
        .where(ProfileRecord.summary_level == SummaryLevel.NONE.value)
        .where(ProfileRecord.kind.in_(kinds))
        .order_by(ProfileRecord.id)
    )


def fetch_profiles_pending_l1(
    session: Session,
    *,
    kinds: Sequence[str] = ("file", "class"),
    limit: int | None = None,
) -> list[ProfileRecord]:
    stmt = _base_pending_query(kinds)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def load_profiles_by_ids(session: Session, ids: Iterable[str]) -> list[ProfileRecord]:
    id_list = list(ids)
    if not id_list:
        return []
    stmt = select(ProfileRecord).where(ProfileRecord.id.in_(id_list))
    records = session.scalars(stmt).all()
    by_id = {record.id: record for record in records}
    return [by_id[id_] for id_ in id_list if id_ in by_id]


def load_profile(session: Session, profile_id: str) -> ProfileRecord | None:
    stmt = select(ProfileRecord).where(ProfileRecord.id == profile_id)
    return session.scalars(stmt).first()


__all__ = [
    "fetch_profiles_pending_l1",
    "load_profile",
    "load_profiles_by_ids",
]
