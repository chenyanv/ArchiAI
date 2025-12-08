"""Analyze route - submit GitHub URL for analysis."""

from fastapi import APIRouter, HTTPException

from workspace import WorkspaceManager
from workspace.github import GitHubError

from ..schemas import AnalyzeRequest, AnalyzeResponse

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    """Submit a GitHub repository for analysis.

    Returns workspace_id immediately. Use SSE /workspaces/{id}/stream to track progress.
    """
    try:
        manager = WorkspaceManager()
        workspace = manager.get_or_create(request.github_url)
        return AnalyzeResponse(workspace_id=workspace.workspace_id)
    except GitHubError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create workspace: {e}")
