"""Workspace routes - SSE stream, overview, and drilldown."""

import asyncio
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from component_agent.graph import run_component_agent
from component_agent.schemas import (
    ComponentDrilldownRequest,
    NavigationBreadcrumb,
    coerce_subagent_payload,
)
from orchestration_agent.graph import run_orchestration_agent
from workspace import WorkspaceManager

from ..schemas import (
    ComponentDTO,
    DrilldownRequest,
    DrilldownResponse,
    NavigationNodeDTO,
    SystemOverviewDTO,
    WorkspaceOverviewResponse,
)

router = APIRouter()


def _get_workspace(workspace_id: str):
    """Get workspace by ID or raise 404."""
    parts = workspace_id.split("-", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid workspace_id format")
    owner, repo = parts
    manager = WorkspaceManager()
    workspace = manager.get(owner, repo)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


async def _stream_analysis(workspace_id: str) -> AsyncGenerator[str, None]:
    """Generate SSE events for analysis progress."""

    def sse_event(status: str, message: str = "", data: Optional[Dict] = None) -> str:
        payload = {"status": status, "message": message}
        if data:
            payload["data"] = data
        return f"data: {json.dumps(payload)}\n\n"

    workspace = _get_workspace(workspace_id)

    # Step 1: Check/build index
    yield sse_event("indexing", "Building structural index...")
    await asyncio.sleep(0)  # Yield control

    if not workspace.is_indexed:
        try:
            loop = asyncio.get_event_loop()
            count = await loop.run_in_executor(None, workspace.build_index)
            yield sse_event("indexing", f"Indexed {count} profiles")
        except Exception as e:
            yield sse_event("error", f"Indexing failed: {e}")
            return
    else:
        yield sse_event("indexing", "Using cached index")

    # Step 2: Run orchestration agent
    yield sse_event("orchestrating", "Analyzing architecture...")
    await asyncio.sleep(0)

    try:
        loop = asyncio.get_event_loop()
        plan = await loop.run_in_executor(
            None,
            lambda: run_orchestration_agent(
                workspace.workspace_id,
                workspace.database_url,
                debug=False,
            ),
        )
    except Exception as e:
        yield sse_event("error", f"Orchestration failed: {e}")
        return

    # Step 3: Return result
    overview = plan.get("system_overview", {})
    cards = plan.get("component_cards", [])

    yield sse_event(
        "done",
        f"Found {len(cards)} components",
        {
            "system_overview": overview,
            "components": cards,
        },
    )


@router.get("/{workspace_id}/stream")
async def stream_analysis(workspace_id: str):
    """SSE stream for analysis progress."""
    return StreamingResponse(
        _stream_analysis(workspace_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/{workspace_id}/overview", response_model=WorkspaceOverviewResponse)
async def get_overview(workspace_id: str):
    """Get workspace overview (cached orchestration result)."""
    workspace = _get_workspace(workspace_id)

    # Try to load cached plan
    plan = None
    if workspace.plan_path.exists():
        try:
            with workspace.plan_path.open() as f:
                plan = json.load(f)
        except Exception:
            pass

    if not plan or not plan.get("component_cards"):
        raise HTTPException(
            status_code=404,
            detail="No analysis found. Use /stream to run analysis first.",
        )

    overview = plan.get("system_overview", {})
    cards = plan.get("component_cards", [])

    return WorkspaceOverviewResponse(
        workspace_id=workspace_id,
        system_overview=SystemOverviewDTO(
            headline=overview.get("headline", ""),
            key_workflows=overview.get("key_workflows", []),
        ),
        components=[
            ComponentDTO(
                component_id=c.get("component_id", ""),
                module_name=c.get("module_name", ""),
                business_signal=c.get("business_signal", ""),
                confidence=c.get("confidence", "medium"),
                objective=c.get("objective", []),
                leading_landmarks=c.get("leading_landmarks", []),
            )
            for c in cards
        ],
    )


@router.post("/{workspace_id}/drilldown", response_model=DrilldownResponse)
async def drilldown(workspace_id: str, request: DrilldownRequest):
    """Drill down into a component or node."""
    workspace = _get_workspace(workspace_id)

    # Build component card for the request
    if request.component_card:
        component_card = request.component_card
    else:
        # Try to find component from cached plan
        plan = None
        if workspace.plan_path.exists():
            with workspace.plan_path.open() as f:
                plan = json.load(f)

        if not plan:
            raise HTTPException(status_code=400, detail="component_card required")

        # Find the component that contains this node
        component_card = None
        for card in plan.get("component_cards", []):
            component_card = card
            break

        if not component_card:
            raise HTTPException(status_code=400, detail="component_card required")

    # Convert breadcrumbs
    breadcrumbs = [
        NavigationBreadcrumb.model_validate(b) for b in request.breadcrumbs
    ]

    # Build request
    drilldown_request = ComponentDrilldownRequest(
        component_card=component_card,
        breadcrumbs=breadcrumbs,
        subagent_payload=coerce_subagent_payload(component_card),
        workspace_id=workspace_id,
        database_url=workspace.database_url,
    )

    # Run component agent
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: run_component_agent(drilldown_request)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Drilldown failed: {e}")

    # Convert to DTO
    return DrilldownResponse(
        component_id=response.component_id,
        agent_goal=response.agent_goal,
        focus_label=response.next_layer.focus_label,
        rationale=response.next_layer.rationale,
        is_sequential=response.next_layer.is_sequential,
        nodes=[
            NavigationNodeDTO(
                node_key=n.node_key,
                title=n.title,
                node_type=n.node_type,
                description=n.description,
                action_kind=n.action.kind,
                target_id=n.action.target_id,
                sequence_order=n.sequence_order,
            )
            for n in response.next_layer.nodes
        ],
        breadcrumbs=[b.model_dump() for b in response.breadcrumbs],
    )
