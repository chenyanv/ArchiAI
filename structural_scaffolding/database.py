from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime
from functools import lru_cache
from typing import Iterable, Optional

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from structural_scaffolding.models import Profile


# Default points to the Docker-exposed PostgreSQL port for local development.
# Containers override this via STRUCTURAL_SCAFFOLD_DB_URL.
DEFAULT_DATABASE_URL = "postgresql+psycopg://archai:archai@localhost:55432/structural_scaffolding"


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


class WorkflowEntryPointRecord(Base):
    """SQLAlchemy representation of a detected workflow entry point."""

    __tablename__ = "workflow_entry_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    entry_point_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[str] = mapped_column(String(50), nullable=False)
    context: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class WorkflowRecord(Base):
    """SQLAlchemy representation of a synthesized workflow."""

    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_point_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    workflow_name: Mapped[Optional[str]] = mapped_column(String(255))
    workflow: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DirectorySummaryRecord(Base):
    """Directory-level aggregation of file summaries."""

    __tablename__ = "directory_summaries"
    __table_args__ = (
        UniqueConstraint("root_path", "directory_path", name="uq_directory_summaries_root_dir"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    directory_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_files: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def resolve_database_url(database_url: str | None) -> str:
    return database_url or os.getenv("STRUCTURAL_SCAFFOLD_DB_URL") or DEFAULT_DATABASE_URL


@lru_cache(maxsize=None)
def _session_factory_for(database_url: str) -> sessionmaker[Session]:
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def create_session(database_url: str | None = None) -> Session:
    url = resolve_database_url(database_url)
    factory = _session_factory_for(url)
    return factory()


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

    session = create_session(database_url)

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
    "create_session",
    "persist_profiles",
    "ProfileRecord",
    "resolve_database_url",
    "WorkflowEntryPointRecord",
    "WorkflowRecord",
    "DirectorySummaryRecord",
]
