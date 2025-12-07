"""LangGraph tool for retrieving the source code captured for a structural profile."""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from structural_scaffolding.database import ProfileRecord, create_session


class GetSourceCodeInput(BaseModel):
    node_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the structural profile (function, method, class, or file) whose source code should be returned.",
    )


def _get_source_code_impl(node_id: str, workspace_id: str, database_url: str | None) -> Dict[str, Any]:
    """Core implementation for get_source_code."""
    normalised_id = node_id.strip()
    if not normalised_id:
        raise ValueError("node_id cannot be blank.")

    try:
        session = create_session(database_url)
    except SQLAlchemyError as exc:
        raise RuntimeError("Unable to open a structural scaffolding database session.") from exc

    try:
        stmt = select(ProfileRecord).where(ProfileRecord.workspace_id == workspace_id, ProfileRecord.id == normalised_id)
        record = session.execute(stmt).scalar_one_or_none()
    finally:
        session.close()

    if record is None:
        raise ValueError(f"Node '{normalised_id}' was not found in workspace '{workspace_id}'.")

    return {
        "code": record.source_code,
        "start_line": record.start_line,
        "end_line": record.end_line,
        "file_path": record.file_path,
    }


def build_get_source_code_tool(workspace_id: str, database_url: str | None = None) -> BaseTool:
    """Create a get_source_code tool bound to a specific workspace."""

    @tool(args_schema=GetSourceCodeInput)
    def get_source_code(node_id: str) -> Dict[str, Any]:
        """Return the source code snippet and line bounds recorded for a structural profile node.

        Supports file, function, method, and class nodes - all retrieved from the database.
        """
        return _get_source_code_impl(node_id, workspace_id, database_url)

    return get_source_code


__all__ = ["GetSourceCodeInput", "build_get_source_code_tool"]
