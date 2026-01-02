"""Workspace routes - SSE stream, overview, and drilldown."""

import asyncio
import json
import os
import queue
import re
import threading
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple, TypeVar

# Enable raw log output with DEBUG=true environment variable
RAW_LOG_MODE = os.getenv("DEBUG", "").lower() in ("true", "1", "yes")

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from component_agent.graph import run_component_agent
from component_agent.schemas import (
    ComponentDrilldownRequest,
    NavigationBreadcrumb,
    coerce_subagent_payload,
)
from drilldown_cache import BreadcrumbCache
from orchestration_agent.graph import run_orchestration_agent
from workspace import WorkspaceManager

from ..schemas import (
    ComponentDTO,
    DrilldownRequest,
    DrilldownResponse,
    NavigationNodeDTO,
    SemanticMetadataDTO,
    SystemOverviewDTO,
    WorkspaceOverviewResponse,
)


def to_title_case(s: str) -> str:
    """Convert kebab-case to Title Case."""
    return " ".join(word.capitalize() for word in s.split("-"))


def group_by_layer(
    components: List[Dict[str, Any]],
    layer_order: List[str]
) -> List[Dict[str, Any]]:
    """Group components by architecture_layer, ordered by layer_order.

    Layout is determined by layer_order, not by call relationships.
    """
    if not layer_order:
        # Fallback: if no layer_order, group all components together
        for card in components:
            card["rank"] = 0
        return [{
            "rank": 0,
            "label": "Components",
            "components": components
        }]

    # Build layer -> rank mapping
    layer_to_rank = {layer: idx for idx, layer in enumerate(layer_order)}

    # Group components by their architecture_layer
    groups: Dict[str, List[Dict[str, Any]]] = {layer: [] for layer in layer_order}
    ungrouped: List[Dict[str, Any]] = []

    for card in components:
        layer = card.get("architecture_layer", "")
        if layer in groups:
            card["rank"] = layer_to_rank[layer]
            groups[layer].append(card)
        else:
            # Component has unknown layer, put at the end
            card["rank"] = len(layer_order)
            ungrouped.append(card)

    # Build result in layer_order sequence
    result = []
    for idx, layer in enumerate(layer_order):
        if groups[layer]:
            result.append({
                "rank": idx,
                "label": to_title_case(layer),
                "components": groups[layer]
            })

    # Add ungrouped components at the end if any
    if ungrouped:
        result.append({
            "rank": len(layer_order),
            "label": "Other",
            "components": ungrouped
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


def _parse_log_message(log: str, raw_mode: bool = False) -> Optional[str]:
    """Parse agent log into user-friendly message. Returns None if not displayable.

    If raw_mode=True, prints all logs to stdout for debugging.
    """
    # Always print raw logs in debug mode
    if raw_mode:
        print(f"[RAW] {log}", flush=True)

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
            message = _parse_log_message(log, raw_mode=RAW_LOG_MODE)
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

    # Step 4: Return result with pre-grouped components by layer
    overview = plan.get("system_overview", {}) if plan else {}
    layer_order = plan.get("layer_order", []) if plan else []
    cards = plan.get("component_cards", []) if plan else []
    business_flow = plan.get("business_flow", []) if plan else []
    token_metrics = plan.get("token_metrics", {}) if plan else {}

    # Group components by architecture_layer (ordered by layer_order)
    ranked_components = group_by_layer(cards, layer_order)
    total_components = sum(len(g["components"]) for g in ranked_components)

    # ✨ Include token metrics in the done event
    event_data = {
        "system_overview": overview,
        "ranked_components": ranked_components,
        "business_flow": business_flow,
    }
    # Always include token_metrics if present (not just when truthy, since empty dicts are falsy)
    if token_metrics is not None and isinstance(token_metrics, dict):
        event_data["token_metrics"] = token_metrics

    total_tokens = token_metrics.get('total_tokens', 0) if isinstance(token_metrics, dict) else 0
    yield _sse_event(
        "done",
        f"Found {total_components} components | Used {total_tokens} tokens",
        event_data,
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
    token_metrics = plan.get("token_metrics", {})

    def _convert_semantic_metadata(semantic_dict: dict | None) -> SemanticMetadataDTO | None:
        """Convert semantic_metadata from plan to API format."""
        if not semantic_dict:
            return None
        return SemanticMetadataDTO(**semantic_dict)

    # ✨ Convert token_metrics to TokenMetrics object
    metrics_obj = None
    if token_metrics:
        from ..schemas import TokenMetrics
        metrics_obj = TokenMetrics(**token_metrics)

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
                semantic_metadata=_convert_semantic_metadata(c.get("semantic_metadata")),
            )
            for c in cards
        ],
        token_metrics=metrics_obj,
    )


# === Drilldown ===


def _build_drilldown_request(
    workspace_id: str, database_url: str, component_card: Dict, breadcrumbs: List[Dict], cache_id: Optional[str] = None, clicked_node: Optional[Dict] = None
) -> Tuple[ComponentDrilldownRequest, str]:
    """Build a ComponentDrilldownRequest from API inputs.

    Returns (request, cache_id) tuple. If cache_id not provided, uses breadcrumbs list.
    If cache_id provided, loads breadcrumbs from cache and returns potentially updated cache_id.
    If clicked_node provided, appends it to breadcrumbs to track drilldown path.
    """
    # Load breadcrumbs from cache if cache_id provided
    if cache_id:
        loaded = BreadcrumbCache.load_breadcrumbs(workspace_id, cache_id)
        if loaded is None:
            raise ValueError(f"Cache {cache_id} not found or expired")
        breadcrumbs = loaded

    # If user clicked a node, add it to breadcrumbs to track drilldown depth
    if clicked_node:
        breadcrumbs = breadcrumbs + [{
            "node_key": clicked_node.get("node_key", ""),
            "title": clicked_node.get("title", ""),
            "node_type": clicked_node.get("node_type", ""),
            "target_id": clicked_node.get("target_id"),
            "metadata": {"action_parameters": clicked_node.get("action_parameters")} if clicked_node.get("action_parameters") else {}
        }]

    # Convert dicts to NavigationBreadcrumb objects
    breadcrumb_objects = [
        NavigationBreadcrumb(
            node_key=b.get("node_key", ""),
            title=b.get("title", b.get("label", "")),  # Support both "title" and "label" for backwards compat
            node_type=b.get("node_type", ""),
            target_id=b.get("target_id"),
            metadata=b.get("metadata", {}),
        )
        for b in breadcrumbs
    ]

    request = ComponentDrilldownRequest(
        component_card=component_card,
        breadcrumbs=breadcrumb_objects,
        subagent_payload=coerce_subagent_payload(component_card),
        workspace_id=workspace_id,
        database_url=database_url,
    )

    # Save updated breadcrumbs to cache and return cache_id
    current_cache_id = BreadcrumbCache.save_breadcrumbs(workspace_id, breadcrumbs)
    return request, current_cache_id


def _validate_action_kind(action_kind: str, node_type: str) -> str:
    """Pass through validated action_kind from component agent.

    The NavigationNode schema validator (in component_agent/schemas.py)
    enforces that action_kind matches node_type:
    - Drillable types (class, workflow, etc.) → "component_drilldown"
    - Non-drillable types → "inspect_source"
    """
    return action_kind


def _batch_validate_target_ids(target_ids: List[Optional[str]], workspace_id: str, database_url: str | None) -> Dict[str, bool]:
    """Batch validate multiple target_ids in a single database query.

    Returns a dict mapping target_id -> bool (whether it exists).
    This replaces N individual queries with a single batch query.
    """
    # Filter out None values to avoid querying for them
    ids_to_check = [tid for tid in target_ids if tid]
    if not ids_to_check:
        return {}

    try:
        from structural_scaffolding.database import ProfileRecord, create_session
        from sqlalchemy import select

        session = create_session(database_url)
        try:
            # Single query to fetch all matching records
            results = session.execute(
                select(ProfileRecord.id).where(
                    ProfileRecord.workspace_id == workspace_id,
                    ProfileRecord.id.in_(ids_to_check),
                )
            ).scalars().all()

            # Return set of valid IDs for fast lookup
            return {tid: True for tid in results}
        finally:
            session.close()
    except Exception:
        # If validation fails, return empty dict (treat all as invalid to be safe)
        return {}


def _validate_target_id(target_id: Optional[str], workspace_id: str, database_url: str | None) -> Optional[str]:
    """Validate that target_id exists in the database before returning it.

    If the node doesn't exist in ProfileRecord, return None to prevent 404 errors.
    The frontend will then use component_drilldown instead of inspect_source.

    Note: For batch validation, use _batch_validate_target_ids() instead.
    """
    if not target_id:
        return None

    try:
        from structural_scaffolding.database import ProfileRecord, create_session
        from sqlalchemy import select

        session = create_session(database_url)
        try:
            exists = session.execute(
                select(ProfileRecord).where(
                    ProfileRecord.workspace_id == workspace_id,
                    ProfileRecord.id == target_id,
                )
            ).scalar_one_or_none()
            return target_id if exists else None
        finally:
            session.close()
    except Exception:
        # If validation fails, return None to be safe
        return None


def _format_drilldown_response(response, workspace_id: str, cache_id: str, database_url: str | None = None) -> Dict:
    """Format component agent response as API dict.

    Args:
        response: Agent response
        workspace_id: Workspace ID for cache storage
        cache_id: Current cache ID for breadcrumbs
        database_url: Database URL for validating target_ids
    """
    # Save agent's updated breadcrumbs to cache to get new cache_id for next drilldown
    breadcrumb_dicts = [b.model_dump() for b in response.breadcrumbs]
    new_cache_id = BreadcrumbCache.save_breadcrumbs(workspace_id, breadcrumb_dicts)

    # OPTIMIZATION: Batch validate all target_ids in a single query (was N+1 queries)
    target_ids = [n.action.target_id for n in response.next_layer.nodes]
    valid_target_ids = _batch_validate_target_ids(target_ids, workspace_id, database_url)

    def _format_node(n):
        """Convert NavigationNode to API dict, including semantic metadata."""
        # Use pre-validated target_id from batch query
        target_id = n.action.target_id if n.action.target_id in valid_target_ids else None

        node_dict = {
            "node_key": n.node_key,
            "title": n.title,
            "node_type": n.node_type,
            "description": n.description,
            "action_kind": _validate_action_kind(n.action.kind, n.node_type),
            "target_id": target_id,
            "action_parameters": n.action.parameters,  # Preserve virtual node context
            "sequence_order": n.sequence_order,
        }

        # Add semantic metadata if present, converting Enums to strings
        if n.semantic_metadata:
            node_dict["semantic_metadata"] = {
                "semantic_role": n.semantic_metadata.semantic_role.value if n.semantic_metadata.semantic_role else None,
                "business_context": n.semantic_metadata.business_context,
                "business_significance": n.semantic_metadata.business_significance,
                "flow_position": n.semantic_metadata.flow_position.value if n.semantic_metadata.flow_position else None,
                "risk_level": n.semantic_metadata.risk_level.value if n.semantic_metadata.risk_level else None,
                "dependencies_description": n.semantic_metadata.dependencies_description,
                "impacted_workflows": n.semantic_metadata.impacted_workflows,
            }

        # Add business narrative if present
        if n.business_narrative:
            node_dict["business_narrative"] = n.business_narrative

        return node_dict

    result = {
        "component_id": response.component_id,
        "agent_goal": response.agent_goal,
        "focus_label": response.next_layer.focus_label,
        "rationale": response.next_layer.rationale,
        "is_sequential": response.next_layer.is_sequential,
        "nodes": [_format_node(n) for n in response.next_layer.nodes],
        "cache_id": new_cache_id,  # Return new cache_id for next drilldown
    }

    # ✨ Include token metrics if present (Scout + Drill combined)
    if response.token_metrics:
        result["token_metrics"] = {
            "prompt_tokens": response.token_metrics.prompt_tokens,
            "completion_tokens": response.token_metrics.completion_tokens,
            "total_tokens": response.token_metrics.total_tokens,
            "estimated_cost": response.token_metrics.estimated_cost,
        }

    return result


async def _stream_drilldown(
    workspace_id: str, component_card: Dict, breadcrumbs: List[Dict], cache_id: Optional[str] = None, clicked_node: Optional[Dict] = None
) -> AsyncGenerator[str, None]:
    """Generate SSE events for drilldown progress."""
    workspace = _get_workspace(workspace_id)

    yield _sse_event("thinking", "Analyzing component structure...")
    await asyncio.sleep(0)

    try:
        drilldown_request, cache_id = _build_drilldown_request(
            workspace_id, workspace.database_url, component_card, breadcrumbs, cache_id, clicked_node
        )
    except ValueError as e:
        yield _sse_event("error", f"Invalid cache: {e}")
        return

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
        _format_drilldown_response(response, workspace_id, cache_id, workspace.database_url),
    )


@router.post("/{workspace_id}/drilldown/stream")
async def drilldown_stream(workspace_id: str, request: DrilldownRequest):
    """SSE stream for drilldown progress."""
    if not request.component_card:
        raise HTTPException(status_code=400, detail="component_card required")

    return StreamingResponse(
        _stream_drilldown(workspace_id, request.component_card, request.breadcrumbs, request.cache_id, request.clicked_node),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/{workspace_id}/drilldown", response_model=DrilldownResponse)
async def drilldown(workspace_id: str, request: DrilldownRequest):
    """Drill down into a component or node (non-streaming)."""
    workspace = _get_workspace(workspace_id)

    if not request.component_card:
        raise HTTPException(status_code=400, detail="component_card required")

    try:
        drilldown_request, cache_id = _build_drilldown_request(
            workspace_id, workspace.database_url, request.component_card, request.breadcrumbs, request.cache_id, request.clicked_node
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid cache: {e}")

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: run_component_agent(drilldown_request)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Drilldown failed: {e}")

    data = _format_drilldown_response(response, workspace_id, cache_id, workspace.database_url)
    return DrilldownResponse(
        component_id=data["component_id"],
        agent_goal=data["agent_goal"],
        focus_label=data["focus_label"],
        rationale=data["rationale"],
        is_sequential=data["is_sequential"],
        nodes=[NavigationNodeDTO(**n) for n in data["nodes"]],
        cache_id=data["cache_id"],
        token_metrics=TokenMetrics(**data["token_metrics"]) if data.get("token_metrics") else None,
    )
