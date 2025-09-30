from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import Integer, String, Text, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from structural_scaffolding.models import Profile


DEFAULT_DATABASE_URL = "postgresql+psycopg:///structural_scaffolding"


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


class ProfileRecord(Base):
    """SQLAlchemy representation of a structural profile."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    function_name: Mapped[Optional[str]] = mapped_column(String)
    class_name: Mapped[Optional[str]] = mapped_column(String)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(String)
    docstring: Mapped[Optional[str]] = mapped_column(Text)
    summary_level: Mapped[str] = mapped_column(String, nullable=False)
    summaries: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    parameters: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    calls: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    children: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)


def resolve_database_url(database_url: str | None) -> str:
    return database_url or os.getenv("STRUCTURAL_SCAFFOLD_DB_URL") or DEFAULT_DATABASE_URL


def _create_session(database_url: str) -> Session:
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def persist_profiles(
    profiles: Iterable[Profile],
    *,
    root: Path,
    database_url: str | None = None,
) -> int:
    """Persist profiles into PostgreSQL using SQLAlchemy.

    Profiles are merged on their primary key, ensuring reruns update existing rows
    without creating duplicates.
    """

    url = resolve_database_url(database_url)
    session = _create_session(url)

    stored = 0
    try:
        for profile in profiles:
            payload = profile.to_dict()
            record = ProfileRecord(
                id=payload["id"],
                root_path=str(Path(root).resolve()),
                kind=payload["kind"],
                file_path=payload["file_path"],
                function_name=payload.get("function_name"),
                class_name=payload.get("class_name"),
                start_line=payload["start_line"],
                end_line=payload["end_line"],
                source_code=payload["source_code"],
                parent_id=payload.get("parent_id"),
                docstring=payload.get("docstring"),
                summary_level=payload["summary_level"],
                summaries=payload.get("summaries", {}),
                parameters=payload.get("parameters", []),
                calls=payload.get("calls", []),
                children=payload.get("children", []),
                data=payload,
            )
            session.merge(record)
            stored += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return stored


__all__ = [
    "DEFAULT_DATABASE_URL",
    "persist_profiles",
    "ProfileRecord",
    "resolve_database_url",
]
