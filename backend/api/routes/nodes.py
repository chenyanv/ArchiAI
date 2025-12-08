"""Node routes - source code retrieval."""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from structural_scaffolding.database import ProfileRecord, create_session

from ..schemas import SourceCodeResponse

router = APIRouter()


@router.get("/{node_id:path}/source", response_model=SourceCodeResponse)
async def get_source(
    node_id: str,
    workspace_id: str = Query(..., description="Workspace ID"),
):
    """Get source code for a node.

    This is a direct database lookup - no LLM involved.
    """
    if not node_id.strip():
        raise HTTPException(status_code=400, detail="node_id cannot be empty")

    try:
        session = create_session(None)
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    try:
        stmt = select(ProfileRecord).where(
            ProfileRecord.workspace_id == workspace_id,
            ProfileRecord.id == node_id,
        )
        record = session.execute(stmt).scalar_one_or_none()
    finally:
        session.close()

    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Node '{node_id}' not found in workspace '{workspace_id}'",
        )

    return SourceCodeResponse(
        node_id=node_id,
        code=record.source_code or "",
        file_path=record.file_path or "",
        start_line=record.start_line,
        end_line=record.end_line,
    )
