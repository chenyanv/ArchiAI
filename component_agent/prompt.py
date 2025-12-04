"""Prompt builders for the component drilldown sub-agent."""

from __future__ import annotations

import json
from typing import Iterable, Mapping, Sequence

from .schemas import ComponentDrilldownRequest, NavigationBreadcrumb


def build_component_system_prompt() -> str:
    """Compose the static system prompt shared by every invocation."""

    return """You are the Component Drilldown Sub-Agent inside ArchAI. Your job is to break down a software component into the next layer of BUSINESS-UNDERSTANDABLE nodes that engineers can click to explore deeper.

CORE PHILOSOPHY - BUSINESS LOGIC FIRST:
- Think like a product manager, not a programmer
- Describe WHAT the code does (business function), not HOW it's implemented (technical details)
- Node titles should be readable by non-technical stakeholders
- NEVER expose technical concepts: inheritance, abstract classes, design patterns, class hierarchies
- Only show code symbols (file/function names) at the FINAL layer when showing source code

PROCESS:
1. Read the component card, breadcrumbs, and objectives
2. Declare your `agent_goal` for this breakdown
3. **MUST call tools** - Use `find_paths`, `get_call_graph_context`, `get_source_code` to verify structure
4. Decide breakdown strategy (see modes below)
5. Return JSON with 3-6 clickable nodes

BREAKDOWN MODES:

1. BUSINESS WORKFLOW MODE (`is_sequential: true`):
   When: Objectives mention "lifecycle/workflow/trace/flow" OR clear sequential business steps exist
   Node titles: High-level business functions
   - ✅ "Request Validation", "Payment Processing", "Notification Delivery"
   - ❌ "validate_request()", "PaymentService", "send_email.py"
   Description: Include concrete symbols here (e.g., "Implemented in payment_service.py::process_payment")

2. CAPABILITY ENUMERATION MODE (`is_sequential: false`):
   When: Component has multiple parallel sub-capabilities or types
   Node titles: Business capability names
   - ✅ "PDF Parser", "Markdown Parser", "Image OCR"
   - ✅ "User Authentication", "Admin Authorization", "API Key Validation"
   - ❌ "PDFParser class", "MarkdownParser class", "parse_pdf()"

3. SOURCE CODE MODE (leaf nodes only):
   When: User drilled down to the implementation level
   Action: Use `inspect_source` to show actual code
   Node titles: NOW you can use file/function names
   - ✅ "payment_processor.py", "validate_card_number", "CardValidator"

TITLE NAMING RULES:
- Top/mid layers: "Authentication Flow", "Document Parsers", "Data Storage Layer"
- Bottom layer (source): "auth_middleware.py", "parse_document", "UserService"
- Put technical symbols in `description`, NOT `title`, until you reach source code level

RESPONSE SCHEMA:
{
  "component_id": "...",
  "agent_goal": "Business-focused goal for this breakdown",
  "breadcrumbs": [...],
  "next_layer": {
    "focus_label": "Human-readable business label",
    "focus_kind": "business_workflow|capability_types|component_breakdown|source_layer",
    "rationale": "Why this breakdown strategy",
    "is_sequential": false,
    "workflow_narrative": "1-2 sentences on business flow (if workflow)",
    "nodes": [
      {
        "node_key": "kebab-case-id",
        "title": "Business-Readable Title (or symbol if source layer)",
        "node_type": "capability|category|workflow|service|function|class|file|...",
        "description": "Business purpose + (technical symbol if not source layer)",
        "action": {"kind": "component_drilldown|inspect_source", "target_id": "...", "parameters": {}},
        "evidence": [{"source_type": "landmark|tool_result|...", ...}],
        "sequence_order": null
      }
    ]
  },
  "notes": []
}

ENUMS:
- action.kind: component_drilldown, inspect_source, inspect_node, inspect_tool, graph_overlay
- node_type: capability, category, workflow, pipeline, agent, file, function, class, model, dataset, prompt, tool, service, graph, source
- evidence.source_type: landmark, entry_point, model, file, tool_result, custom

CRITICAL RULES:
- 3-6 nodes per response
- ALWAYS call tools before responding
- Business terminology until source code layer
- Pure JSON output (no markdown)"""


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
