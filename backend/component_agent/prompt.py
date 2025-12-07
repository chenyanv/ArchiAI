"""Prompt builders for the component drilldown sub-agent.

# TODO: Component Agent improvements needed:
# 1. Distinguish "overview nodes" vs "code nodes" - overview can drilldown, code should inspect_source
# 2. Limit nesting depth - max 2 levels of drilldown, then must show code
# 3. Reduce token usage - currently ~30k tokens per drilldown is too expensive
# 4. Fix navigation logic - selecting a child shouldn't go back to parent concepts
"""

from __future__ import annotations

import json
from typing import Mapping, Sequence

from .schemas import ComponentDrilldownRequest, NavigationBreadcrumb


def build_component_system_prompt() -> str:
    """Compose the static system prompt shared by every invocation."""

    return """You are the Component Drilldown Sub-Agent. Break down a software component into 3-6 navigable nodes for junior engineers to explore.

GOAL: Help engineers understand WHAT exists (business purpose) + HOW it works (implementation) + WHY it's designed this way.

KEY INSIGHT - BE CONCRETE:
- Collections → enumerate actual items (e.g., Glob, Read, Write)
- Processes → enumerate actual steps (e.g., Validate → Process → Notify)
- Each node = something inspectable (code entity or workflow step)
- NOT abstract labels ("File System Tools", "Core Capabilities")

PROCESS:
1. Call `extract_subgraph(node_id, max_depth=2)` using a node_id from `leading_landmarks`
2. Analyze results to identify the concrete entities inside
3. Return 3-6 nodes representing what's actually there

BREAKDOWN MODES:
- `is_sequential: true` → workflow steps (e.g., "Request Validation", "Payment Processing")
- `is_sequential: false` → parallel capabilities (e.g., "PDF Parser", "Auth Service")
- At leaf level → use `inspect_source` to show actual code

RESPONSE FORMAT:
- action.kind: "component_drilldown" (drill deeper) or "inspect_source" (show code)
- Pure JSON output, no markdown

NODE_ID INTEGRITY (CRITICAL):
- ONLY use node_ids returned by tools (`extract_subgraph`, `rank_call_graph_nodes`, etc.)
- NEVER fabricate node_ids - fake IDs don't exist in the graph
- If no real node_id exists, leave `target_id` empty and use descriptive title only"""


def _format_breadcrumbs(breadcrumbs: Sequence[NavigationBreadcrumb]) -> Sequence[Mapping[str, str]]:
    formatted = []
    for crumb in breadcrumbs:
        payload = {
            "node_key": crumb.node_key,
            "title": crumb.title,
            "node_type": crumb.node_type,
        }
        if crumb.target_id:
            payload["target_id"] = crumb.target_id
        if crumb.metadata:
            payload["metadata"] = crumb.metadata
        formatted.append(payload)
    return formatted


def format_component_request(
    request: ComponentDrilldownRequest,
) -> str:
    """Build the user-facing portion of the prompt with dynamic context.

    Note: AVAILABLE TOOLS section removed - tools are already bound via bind_tools().
    Note: Only essential fields from component_card are included to reduce token usage.
    """
    # Extract only essential fields from component_card (no duplicates)
    card = request.component_card
    compact_card = {
        "component_id": card.get("component_id"),
        "module_name": card.get("module_name"),
        "business_signal": card.get("business_signal"),
        "leading_landmarks": card.get("leading_landmarks", []),
        "core_models": card.get("core_models", []),
    }
    # Only include entry_points if non-empty
    entry_points = card.get("primary_entry_points", [])
    if entry_points:
        compact_card["primary_entry_points"] = entry_points

    payload = {
        "component_card": compact_card,
        "breadcrumbs": _format_breadcrumbs(request.breadcrumbs),
        "objectives": (request.subagent_payload or {}).get("objective", []),
    }
    formatted_payload = json.dumps(payload, ensure_ascii=False, indent=2)

    return f"""# COMPONENT CONTEXT
{formatted_payload}

# TASK
Use tools to explore the codebase, then respond with JSON only.
"""


__all__ = [
    "build_component_system_prompt",
    "format_component_request",
]
