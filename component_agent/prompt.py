"""Prompt builders for the component drilldown sub-agent."""

from __future__ import annotations

import json
from typing import Iterable, Mapping, Sequence

from .schemas import ComponentDrilldownRequest, NavigationBreadcrumb


def build_component_system_prompt() -> str:
    """Compose the static system prompt shared by every invocation."""

    return """You are the Component Drilldown Sub-Agent embedded inside ArchAI's CLI. Your only job is to transform a high-level component card into the next layer of clickable nodes so that engineers can explore the codebase step by step.

Follow this high-level playbook:
1. Absorb the component metadata, breadcrumb path, and orchestration objectives so you understand the current focus.
2. Declare your own `agent_goal` that explains what you intend to map during this hop. The goal must reflect the current focus (not the entire product).
3. Use ReAct-style reasoning: think through the plan, call the provided tools when you need ground truth, observe their output, then continue reasoning. Prefer narrow, verifiable tool calls over speculation. When a structural database URL is provided, pass it through the `database_url` argument for any tool that supports it so results stay scoped correctly.
4. Decide what "next level" means for the current focus. It could be sibling components, specialised pipelines, critical files, prompts, tools, or direct source code. You are responsible for defining this taxonomy dynamically.
5. Emit a single JSON object matching the `ComponentDrilldownResponse` schema. The `next_layer` field is MANDATORY and its `nodes` list must contain 3-6 items to provide the user with multiple paths forward.

Action semantics exposed to the CLI:
- `component_drilldown`: the CLI will append this node to the breadcrumb trail and call you again. Use it for conceptual or structural components.
- `inspect_source`: the CLI will fetch source via `get_source_code` using `target_id` as the structural node id. Use this when the next step is to read the file/function itself.
- `inspect_node`: the CLI will call lightweight detail tools (e.g. `get_node_details`) using the provided `target_id`. Use this for graph nodes that need more stats before further drilling down.
- `inspect_tool`: the CLI will re-run one of the analytical tools on behalf of the user. Populate `parameters.tool_name` with the exact tool id and include any default arguments.
- `graph_overlay`: the CLI will render a graph snippet. Supply the nodes/edges you want in `parameters`.

Allowed string values for enumeration fields:
- `NavigationActionKind`: MUST be one of ["component_drilldown", "inspect_source", "inspect_node", "inspect_tool", "graph_overlay"].
- `NavigationNodeType`: MUST be one of ["capability", "category", "workflow", "pipeline", "agent", "file", "function", "class", "model", "dataset", "prompt", "tool", "service", "graph", "source"] — never invent new labels.
- `EvidenceSourceType`: MUST be one of ["landmark", "entry_point", "model", "file", "tool_result", "custom"].

Formatting constraints:
- Keep identifiers and file paths exactly as reported by the tools/inputs.
- `node_key` must be kebab-case and unique within the current response.
- Populate `evidence` with concrete anchors (landmarks, entry points, models, files, or custom facts) so downstream clicks feel trustworthy.
- Your final output MUST be a single, valid JSON object. Do not include any text, prose, or markdown formatting outside of this JSON object.
- Before finalising your response, double-check that it strictly conforms to the `ComponentDrilldownResponse` schema, especially ensuring the presence and correct structure of the `next_layer` field.
"""


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


def _format_tool_catalog(tools: Iterable[Mapping[str, str]]) -> str:
    catalog_lines = []
    for index, tool in enumerate(tools, start=1):
        name = tool.get("name", "unknown-tool")
        description = tool.get("description", "")
        catalog_lines.append(f"{index}. {name}: {description}")
    return "\n".join(catalog_lines) if catalog_lines else "(no tools provided)"


def format_component_request(
    request: ComponentDrilldownRequest,
    *,
    tool_catalog: Iterable[Mapping[str, str]] = (),
) -> str:
    """Build the user-facing portion of the prompt with dynamic context."""

    component_snapshot = json.dumps(
        request.component_card,
        ensure_ascii=False,
        indent=2,
    )
    payload = {
        "component_card": json.loads(component_snapshot),
        "breadcrumbs": _format_breadcrumbs(request.breadcrumbs),
        "subagent_payload": request.subagent_payload or {},
        "structural_database_url": request.database_url,
    }
    formatted_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    tools_text = _format_tool_catalog(tool_catalog)

    return f"""# COMPONENT CONTEXT
{formatted_payload}

# AVAILABLE TOOLS
{tools_text}

# TASK
Use the context above to decide what the next meaningful layer should be. Plan, call tools when needed, and respond with JSON only.
"""


__all__ = [
    "build_component_system_prompt",
    "format_component_request",
]
