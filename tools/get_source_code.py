"""
LangGraph tool for retrieving the source code captured for a structural profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

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


@dataclass(frozen=True)
class GetSourceCodeTool:
    """
    Fetch a structural profile's source code directly from the persisted database.
    """

    name: str = "get_source_code"
    description: str = (
        "Return the source code snippet and line bounds recorded for a structural "
        "profile node. Intended for sub-agents that require the authoritative code "
        "before continuing their analysis."
    )
    args_schema = GetSourceCodeInput

    def _lookup_profile(
        self,
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

    def _run(
        self,
        node_id: str,
        database_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalised_id = _normalise_node_id(node_id)
        profile = self._lookup_profile(node_id=normalised_id, database_url=database_url)
        return {
            "code": profile.source_code,
            "start_line": profile.start_line,
            "end_line": profile.end_line,
            "file_path": profile.file_path,
        }

    def invoke(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        if isinstance(payload, GetSourceCodeInput):
            params = payload
        elif isinstance(payload, Mapping):
            params = self.args_schema(**payload)
        else:
            raise TypeError("Tool payload must be a mapping or GetSourceCodeInput.")
        return self._run(params.node_id, params.database_url)

    def __call__(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        return self.invoke(payload)


def build_get_source_code_tool() -> GetSourceCodeTool:
    """
    Create a LangGraph-compatible tool that exposes structural source snippets.
    """
    return GetSourceCodeTool()


get_source_code_tool = build_get_source_code_tool()


__all__ = [
    "GetSourceCodeInput",
    "GetSourceCodeTool",
    "build_get_source_code_tool",
    "get_source_code_tool",
]
