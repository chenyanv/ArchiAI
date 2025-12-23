"""Workspace routes - SSE stream, overview, and drilldown."""

import asyncio
import json
import queue
import re
import threading
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple, TypeVar

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


def compute_ranks(
    components: List[Dict[str, Any]],
    business_flow: List[Dict[str, Any]]
) -> Dict[str, int]:
    """Compute layout ranks based on business_flow edges using longest path algorithm."""
    ids = {c["component_id"] for c in components}
    in_edges: Dict[str, List[str]] = {id: [] for id in ids}
    out_edges: Dict[str, List[str]] = {id: [] for id in ids}
    has_edge: set = set()

    # Build adjacency lists
    for edge in business_flow:
        from_id = edge.get("from_component")
        to_id = edge.get("to_component")
        if from_id in ids and to_id in ids:
            out_edges[from_id].append(to_id)
            in_edges[to_id].append(from_id)
            has_edge.add(from_id)
            has_edge.add(to_id)

    # Compute ranks using longest path (BFS from sources)
    ranks: Dict[str, int] = {}
    queue_list: List[str] = []

    # Initialize: nodes with no incoming edges (but have some edge) start at rank 0
    for id in ids:
        if id in has_edge and not in_edges[id]:
            ranks[id] = 0
            queue_list.append(id)

    # Process in topological order
    max_rank = 0
    while queue_list:
        curr = queue_list.pop(0)
        curr_rank = ranks[curr]
        max_rank = max(max_rank, curr_rank)
        for next_id in out_edges[curr]:
            new_rank = curr_rank + 1
            if next_id not in ranks or ranks[next_id] < new_rank:
                ranks[next_id] = new_rank
                max_rank = max(max_rank, new_rank)
                queue_list.append(next_id)

    # Disconnected nodes (no edges at all) go to the last rank
    for id in ids:
        if id not in ranks:
            ranks[id] = max_rank + 1 if max_rank > 0 else 0

    return ranks


def group_by_rank(
    components: List[Dict[str, Any]],
    business_flow: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Group components by computed ranks, returning pre-grouped structure for frontend."""
    ranks = compute_ranks(components, business_flow)

    # Group components by rank
    groups: Dict[int, List[Dict[str, Any]]] = {}
    for card in components:
        rank = ranks.get(card["component_id"], 0)
        card["rank"] = rank  # Keep rank on individual cards for reference
        if rank not in groups:
            groups[rank] = []
        groups[rank].append(card)

    # Sort by rank and build result
    sorted_ranks = sorted(groups.keys())
    max_rank = sorted_ranks[-1] if sorted_ranks else 0

    result = []
    for rank in sorted_ranks:
        # Determine label based on position
        if rank == 0:
            label = "Entry"
        elif rank == max_rank:
            label = "Data"
        else:
            label = f"Layer {rank}"

        result.append({
            "rank": rank,
            "label": label,
            "components": groups[rank]
        })

    return result

router = APIRouter()

T = TypeVar("T")


# === Shared Helpers ===


def _sse_event(status: str, message: str = "", data: Optional[Dict] = None) -> str:
    """Format an SSE event."""
    payload = {"status": status, "message": message}
    if data:
        payload["data"] = data
    return f"data: {json.dumps(payload)}\n\n"


def _parse_log_message(log: str) -> Optional[str]:
    """Parse agent log into user-friendly message. Returns None if not displayable."""
    if log.startswith("[tool:start]"):
        match = re.match(r"\[tool:start\] (\w+)", log)
        return f"Calling {match.group(1)}..." if match else None
    elif log.startswith("[tool:end]"):
        match = re.match(r"\[tool:end\] (\w+)", log)
        return f"Got results from {match.group(1)}" if match else None
    elif log.startswith("[llm:output]"):
        return "Analyzing results..."
    elif log.startswith("[orchestration]"):
        if "Starting" in log:
            return "Starting analysis..."
        elif "completed" in log:
            return "Finalizing components..."
    elif log.startswith("[structured_output]"):
        return "Finalizing navigation nodes..." if "success" in log else "Generating structured response..."
    elif log.startswith("[llm:input]"):
        return "Processing context..."
    return None


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


async def _stream_agent_logs(
    agent_fn: Callable[[Callable[[str], None]], T],
    status: str,
) -> AsyncGenerator[Tuple[str, Optional[T], Optional[Exception]], None]:
    """
    Run an agent in background thread, yielding SSE events for logs.

    Yields tuples of (sse_event, result, error):
    - During streaming: (event_str, None, None)
    - On success: ("", result, None)
    - On error: ("", None, exception)
    """
    log_queue: queue.Queue[Optional[str]] = queue.Queue()
    result_holder: Dict[str, Any] = {}
    error_holder: Dict[str, Exception] = {}

    def run():
        def logger(msg: str):
            log_queue.put(msg)
        try:
            result_holder["result"] = agent_fn(logger)
        except Exception as e:
            error_holder["error"] = e
        finally:
            log_queue.put(None)

    thread = threading.Thread(target=run)
    thread.start()

    last_message = ""
    while True:
        try:
            log = log_queue.get(timeout=0.1)
            if log is None:
                break
            message = _parse_log_message(log)
            if message and message != last_message:
                last_message = message
                yield (_sse_event(status, message), None, None)
                await asyncio.sleep(0)
        except queue.Empty:
            await asyncio.sleep(0.1)

    thread.join()

    if "error" in error_holder:
        yield ("", None, error_holder["error"])
    else:
        yield ("", result_holder.get("result"), None)


# === Analysis Stream ===


async def _stream_analysis(workspace_id: str) -> AsyncGenerator[str, None]:
    """Generate SSE events for analysis progress."""
    workspace = _get_workspace(workspace_id)

    # Step 1: Check/build index
    yield _sse_event("indexing", "Building structural index...")
    await asyncio.sleep(0)

    if not workspace.is_indexed:
        try:
            loop = asyncio.get_event_loop()
            count = await loop.run_in_executor(None, workspace.build_index)
            yield _sse_event("indexing", f"Indexed {count} profiles")
        except Exception as e:
            yield _sse_event("error", f"Indexing failed: {e}")
            return
    else:
        yield _sse_event("indexing", "Using cached index")

    # Step 2: Check for cached orchestration result
    plan = None
    if workspace.plan_path.exists():
        try:
            with workspace.plan_path.open() as f:
                plan = json.load(f)
            yield _sse_event("orchestrating", "Using cached analysis...")
            await asyncio.sleep(0.1)
        except Exception:
            plan = None

    # Step 3: Run orchestration agent if needed
    if not plan or not plan.get("component_cards"):
        yield _sse_event("orchestrating", "Starting analysis...")
        await asyncio.sleep(0)

        async for event, result, error in _stream_agent_logs(
            lambda logger: run_orchestration_agent(
                workspace.workspace_id,
                workspace.database_url,
                debug=True,
                logger=logger,
            ),
            "orchestrating",
        ):
            if event:
                yield event
            elif error:
                yield _sse_event("error", f"Orchestration failed: {error}")
                return
            else:
                plan = result
                # Save plan to disk for future use
                try:
                    workspace.results_dir.mkdir(parents=True, exist_ok=True)
                    with workspace.plan_path.open("w") as f:
                        json.dump(plan, f, indent=2)
                except Exception as e:
                    # Log but don't fail if we can't save
                    print(f"Warning: Failed to cache plan: {e}")

    # Step 4: Return result with pre-grouped ranked components
    overview = plan.get("system_overview", {}) if plan else {}
    cards = plan.get("component_cards", []) if plan else []
    business_flow = plan.get("business_flow", []) if plan else []

    # Group components by rank (computed from business_flow)
    ranked_components = group_by_rank(cards, business_flow)
    total_components = sum(len(g["components"]) for g in ranked_components)

    yield _sse_event(
        "done",
        f"Found {total_components} components",
        {"system_overview": overview, "ranked_components": ranked_components, "business_flow": business_flow},
    )


@router.get("/{workspace_id}/stream")
async def stream_analysis(workspace_id: str):
    """SSE stream for analysis progress."""
    return StreamingResponse(
        _stream_analysis(workspace_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# === Overview ===


@router.get("/{workspace_id}/overview", response_model=WorkspaceOverviewResponse)
async def get_overview(workspace_id: str):
    """Get workspace overview (cached orchestration result)."""
    workspace = _get_workspace(workspace_id)

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


# === Drilldown ===


def _build_drilldown_request(
    workspace_id: str, database_url: str, component_card: Dict, breadcrumbs: List[Dict]
) -> ComponentDrilldownRequest:
    """Build a ComponentDrilldownRequest from API inputs."""
    return ComponentDrilldownRequest(
        component_card=component_card,
        breadcrumbs=[
            NavigationBreadcrumb(
                node_key=b.get("node_key", ""),
                title=b.get("label", ""),
                node_type="",
            )
            for b in breadcrumbs
        ],
        subagent_payload=coerce_subagent_payload(component_card),
        workspace_id=workspace_id,
        database_url=database_url,
    )


def _format_drilldown_response(response) -> Dict:
    """Format component agent response as API dict."""
    return {
        "component_id": response.component_id,
        "agent_goal": response.agent_goal,
        "focus_label": response.next_layer.focus_label,
        "rationale": response.next_layer.rationale,
        "is_sequential": response.next_layer.is_sequential,
        "nodes": [
            {
                "node_key": n.node_key,
                "title": n.title,
                "node_type": n.node_type,
                "description": n.description,
                "action_kind": n.action.kind,
                "target_id": n.action.target_id,
                "sequence_order": n.sequence_order,
            }
            for n in response.next_layer.nodes
        ],
        "breadcrumbs": [b.model_dump() for b in response.breadcrumbs],
    }


async def _stream_drilldown(
    workspace_id: str, component_card: Dict, breadcrumbs: List[Dict]
) -> AsyncGenerator[str, None]:
    """Generate SSE events for drilldown progress."""
    workspace = _get_workspace(workspace_id)

    yield _sse_event("thinking", "Analyzing component structure...")
    await asyncio.sleep(0)

    drilldown_request = _build_drilldown_request(
        workspace_id, workspace.database_url, component_card, breadcrumbs
    )

    response = None
    async for event, result, error in _stream_agent_logs(
        lambda logger: run_component_agent(drilldown_request, logger=logger, debug=True),
        "thinking",
    ):
        if event:
            yield event
        elif error:
            yield _sse_event("error", f"Drilldown failed: {error}")
            return
        else:
            response = result

    if not response:
        yield _sse_event("error", "No response from agent")
        return

    yield _sse_event(
        "done",
        f"Found {len(response.next_layer.nodes)} nodes",
        _format_drilldown_response(response),
    )


@router.post("/{workspace_id}/drilldown/stream")
async def drilldown_stream(workspace_id: str, request: DrilldownRequest):
    """SSE stream for drilldown progress."""
    if not request.component_card:
        raise HTTPException(status_code=400, detail="component_card required")

    return StreamingResponse(
        _stream_drilldown(workspace_id, request.component_card, request.breadcrumbs),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/{workspace_id}/drilldown", response_model=DrilldownResponse)
async def drilldown(workspace_id: str, request: DrilldownRequest):
    """Drill down into a component or node (non-streaming)."""
    workspace = _get_workspace(workspace_id)

    if not request.component_card:
        raise HTTPException(status_code=400, detail="component_card required")

    drilldown_request = _build_drilldown_request(
        workspace_id, workspace.database_url, request.component_card, request.breadcrumbs
    )

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: run_component_agent(drilldown_request)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Drilldown failed: {e}")

    data = _format_drilldown_response(response)
    return DrilldownResponse(
        component_id=data["component_id"],
        agent_goal=data["agent_goal"],
        focus_label=data["focus_label"],
        rationale=data["rationale"],
        is_sequential=data["is_sequential"],
        nodes=[NavigationNodeDTO(**n) for n in data["nodes"]],
        breadcrumbs=data["breadcrumbs"],
    )
