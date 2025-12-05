"""Database models and session management for structural scaffolding."""

from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import DateTime, Index, Integer, PrimaryKeyConstraint, String, Text, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import JSON

from structural_scaffolding.models import Profile


# Default points to the Docker-exposed PostgreSQL port for local development.
DEFAULT_DATABASE_URL = "postgresql+psycopg://archai:archai@localhost:55432/structural_scaffolding"


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


class ProfileRecord(Base):
    """SQLAlchemy representation of a structural profile."""

    __tablename__ = "profiles"

    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    function_name: Mapped[Optional[str]] = mapped_column(String)
    class_name: Mapped[Optional[str]] = mapped_column(String)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(String)
    docstring: Mapped[Optional[str]] = mapped_column(Text)
    parameters: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    calls: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    children: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id"),
        Index("ix_profiles_workspace_kind", "workspace_id", "kind"),
    )


class CallGraphRecord(Base):
    """SQLAlchemy representation of a call graph."""

    __tablename__ = "call_graphs"

    workspace_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    graph_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False)
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


class WorkflowEntryPointRecord(Base):
    """SQLAlchemy representation of a detected workflow entry point."""

    __tablename__ = "workflow_entry_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(255), nullable=False)
    entry_point_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[str] = mapped_column(String(50), nullable=False)
    context: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_workflow_entry_points_workspace_profile", "workspace_id", "profile_id", unique=True),
    )


class WorkflowRecord(Base):
    """SQLAlchemy representation of a synthesized workflow."""

    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entry_point_id: Mapped[str] = mapped_column(String(255), nullable=False)
    workflow_name: Mapped[Optional[str]] = mapped_column(String(255))
    workflow: Mapped[dict] = mapped_column(JSON, nullable=False)
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

    __table_args__ = (
        Index("ix_workflows_workspace_entry", "workspace_id", "entry_point_id", unique=True),
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
    workspace_id: str,
    database_url: str | None = None,
) -> int:
    """Persist profiles into PostgreSQL.

    Profiles are merged on their primary key, ensuring reruns update existing rows.
    """
    session = create_session(database_url)
    stored = 0

    try:
        for profile in profiles:
            payload = profile.to_dict()
            record = ProfileRecord(
                workspace_id=workspace_id,
                id=payload["id"],
                kind=payload["kind"],
                file_path=payload["file_path"],
                function_name=payload.get("function_name"),
                class_name=payload.get("class_name"),
                start_line=payload["start_line"],
                end_line=payload["end_line"],
                source_code=payload["source_code"],
                parent_id=payload.get("parent_id"),
                docstring=payload.get("docstring"),
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


def delete_workspace_data(workspace_id: str, database_url: str | None = None) -> None:
    """Delete all data for a workspace."""
    session = create_session(database_url)
    try:
        session.query(ProfileRecord).filter_by(workspace_id=workspace_id).delete()
        session.query(CallGraphRecord).filter_by(workspace_id=workspace_id).delete()
        session.query(WorkflowEntryPointRecord).filter_by(workspace_id=workspace_id).delete()
        session.query(WorkflowRecord).filter_by(workspace_id=workspace_id).delete()
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = [
    "Base",
    "CallGraphRecord",
    "DEFAULT_DATABASE_URL",
    "create_session",
    "delete_workspace_data",
    "persist_profiles",
    "ProfileRecord",
    "resolve_database_url",
    "WorkflowEntryPointRecord",
    "WorkflowRecord",
]
