"""
LangGraph tool for retrieving the source code captured for a structural profile.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from structural_scaffolding.database import ProfileRecord, create_session


class GetSourceCodeInput(BaseModel):
    node_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Identifier of the structural profile (function, method, class, or file) "
            "whose source code should be returned."
        ),
    )
    database_url: Optional[str] = Field(
        default=None,
        description="Optional override for the structural scaffolding database URL.",
    )


def _normalise_node_id(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("node_id cannot be blank.")
    return cleaned


def _lookup_profile(
    *,
    node_id: str,
    database_url: Optional[str],
) -> ProfileRecord:
    try:
        session = create_session(database_url)
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "Unable to open a structural scaffolding database session."
        ) from exc

    try:
        record = session.get(ProfileRecord, node_id)
    finally:
        session.close()

    if record is None:
        raise ValueError(
            f"Node '{node_id}' was not found in the structural profile database."
        )
    return record


@tool(args_schema=GetSourceCodeInput)
def get_source_code(
    node_id: str,
    database_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the source code snippet and line bounds recorded for a structural profile node.

    Intended for sub-agents that require the authoritative code before continuing their analysis.
    """
    normalised_id = _normalise_node_id(node_id)
    profile = _lookup_profile(node_id=normalised_id, database_url=database_url)
    return {
        "code": profile.source_code,
        "start_line": profile.start_line,
        "end_line": profile.end_line,
        "file_path": profile.file_path,
    }


__all__ = [
    "GetSourceCodeInput",
    "get_source_code",
]
