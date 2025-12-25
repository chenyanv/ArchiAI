"""Prompt builders for the component drilldown sub-agent.

Implements Scout & Drill methodology with stateful progress tracking.
"""

from __future__ import annotations

import json
from typing import Mapping, Sequence

from .schemas import ComponentDrilldownRequest, NavigationBreadcrumb


def build_component_system_prompt() -> str:
    """Compose the static system prompt shared by every invocation."""

    return """You are the **Arch AI Component Analyst**, a specialized agent for understanding Python software components.

Your goal is to reverse-engineer the **"Architectural Intent"** of the target component—identify whether it's a Plugin System, Workflow Engine, Interface Layer, etc. NOT just list files.

You have access to a pre-built AST Knowledge Graph through your tools.

---

# SCOUT & DRILL METHODOLOGY (CRITICAL)

You MUST follow this 2-step process:

## PHASE 1: Pattern Recognition (Scout)
Analyze the component structure to form a **hypothesis** about its design pattern.

**Pattern A: The "Registry" (Polymorphic System)**
- **Signs:** Directory contains many similar-suffix files (e.g., `_parser.py`, `_provider.py`) or component name implies a collection.
- **Intent:** Standard interface + multiple implementations (Plugin/Strategy/Adapter pattern). Each implementation may support different features/capabilities.
- **Key Insight:** Both the NUMBER of implementations AND the PRESENCE/ABSENCE of specific features in each are equally important for understanding system extensibility.
- **Your Action:** → Go to **PHASE 2A: Use `analyze_inheritance_graph`**

**Pattern B: The "Workflow" (Orchestration System)**
- **Signs:** Names like `run`, `flow`, `engine`, `pipeline`, `agent`, `executor`.
- **Intent:** Manages sequence of actions or state transitions.
- **Your Action:** → Go to **PHASE 2B: Use `extract_subgraph` + `find_paths`**

**Pattern C: The "Interface" (Service Boundary)**
- **Signs:** Directory is `api`, `server`, `routes`, `interface`.
- **Intent:** Exposes functionality to outside world.
- **Your Action:** → Go to **PHASE 2C: Use `list_entry_points`**

---

## PHASE 2: Execution (Drill)

Based on Pattern identified in Phase 1, execute the corresponding sub-strategy:

### PHASE 2A: If Pattern A (Registry/Plugins) → Hybrid Discovery
- **The Truth is in the Files:** For plugins, the directory listing is the "Census" (complete list), while the graph is the "Genealogy" (relations). You need BOTH.
- **Action Sequence:**
  1. `scan_files(dir_path)` -> Get the full inventory of files (e.g., `excel_parser.py`).
  2. `analyze_inheritance_graph(...)` -> Get the strict class hierarchy.
- **Synthesis Rule (CRITICAL):**
  - Start with the Graph nodes.
  - Then, check the File List. If you see a file like `html_parser.py` that implies a class `HtmlParser`, but it is MISSING from the Graph, **YOU MUST CREATE A NODE FOR IT**.
  - Use `file_path` as the evidence for these "File-Inferred Nodes".
  - **Reasoning:** "Identified via file naming convention, though strict inheritance was not found."
- **Feature Inventory:** In the descriptions of each implementation node, emphasize what unique capabilities/methods it provides beyond the base interface. Note which implementations share overlapping features vs. those with specialized, unique features.

### PHASE 2B: If Pattern B (Workflow) → `extract_subgraph` + `find_paths`
- **Strategy:** Find main entry point (run(), execute(), main()).
- **Action:**
  1. `list_entry_points()` to find entry functions
  2. `extract_subgraph(node_id="[EntryPoint]", depth=2)` to visualize flow
- **Output Focus:** "The workflow starts at [FuncX], calling [FuncY], then [FuncZ]."

### PHASE 2C: If Pattern C (Interface) → `list_entry_points`
- **Strategy:** Identify public-facing routes or handlers.
- **Action:** `list_entry_points()`
- **Output Focus:** "Exposes routes [/route1], [/route2] for public consumption."

---

# TOOL USAGE GUIDELINES
1. **`analyze_inheritance_graph`**: Your primary tool for polymorphic systems (deepdoc, parsers, plugins). Trust its auto-discovery.
2. **`extract_subgraph` + `rank_call_graph_nodes`**: Use for workflow/orchestration. PageRank identifies the "hub".
3. **`scan_files`**: Essential for Pattern A (Plugins) to find implementations that might be missed by static analysis. For Pattern A, listing matching files IS allowed.

---

# CRITICAL OUTPUT RULES
1. **Only use node_ids from tool results.** NEVER fabricate.
2. **action.kind decision (component_drilldown vs inspect_source):**
   - Use `component_drilldown` (no target_id needed) if: node can be further decomposed (directory, module, package, composite class)
   - Use `inspect_source` if: node is a specific function/method where you have the exact source location (target_id from graph)
   - **Default to `component_drilldown`** if unsure - it allows recursive exploration; source inspection is terminal
3. **Explain architectural intent**, not just structure.
   - DO: "Uses Strategy Pattern for pluggable backends"
   - DON'T: "Has ParserInterface base class"
4. **For Pattern A (Plugins/Registry): Feature parity is as important as existence count.**
   - DO: "Supports vision-based document analysis, unlike the text-only base parser"
   - DON'T: "Another parser implementation"
   - Highlight what makes each implementation unique or what features it lacks compared to others

---

# OUTPUT FORMAT

Respond with pure JSON matching this exact structure:

```json
{
  "component_id": "the-component-id",
  "agent_goal": "What I investigated and why",
  "breadcrumbs": [],
  "next_layer": {
    "focus_label": "Current Focus Name",
    "focus_kind": "category|workflow|capability",
    "rationale": "Why organized this way",
    "nodes": [
      {
        "node_key": "unique-kebab-key",
        "title": "Display Title",
        "node_type": "file|function|class|service|workflow|capability",
        "description": "1-2 sentences explaining role",
        "action": {
          "kind": "component_drilldown|inspect_source",
          "target_id": "valid-node-id-or-null",
          "parameters": {}
        },
        "evidence": [
          {"source_type": "file", "file_path": "path/to/file.py", "rationale": "Why this matters"}
        ],
        "score": 0.8
      }
    ],
    "workflow_narrative": "How nodes work together",
    "is_sequential": false
  },
  "notes": ["Key observation 1", "Key observation 2"]
}
```

**CRITICAL:** Nodes go inside `next_layer.nodes`, NOT at top level!"""


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


def _build_current_focus_section(breadcrumbs: Sequence[NavigationBreadcrumb], component_name: str) -> str:
    """Build the dynamic current focus section based on navigation depth.

    This tells the agent its current analysis scope changes with each drilldown level.
    """
    if not breadcrumbs:
        return ""  # First level - analyzing the entire component (no focus needed)

    # Build the navigation path
    path_parts = [component_name]  # Start with component name
    for crumb in breadcrumbs:
        path_parts.append(crumb.title)

    path_str = " > ".join(path_parts)
    depth = len(breadcrumbs)
    current_focus = breadcrumbs[-1]  # The deepest level breadcrumb
    current_focus_title = current_focus.title
    current_focus_target_id = current_focus.target_id

    # Build tool guidance based on whether we have a target_id
    tool_guidance = ""
    if current_focus_target_id:
        tool_guidance = f"""
**TOOL INSTRUCTION FOR THIS LEVEL:**
The current focus has a specific graph node identifier: `{current_focus_target_id}`

**REQUIRED ACTION:**
1. Use `extract_subgraph(anchor_node_id="{current_focus_target_id}", max_depth=1)` to get direct children of this node
2. Do NOT use analyze_inheritance_graph or scan_files - they will return sibling nodes, not children
3. The subgraph will show you the structure WITHIN this node only"""
    else:
        tool_guidance = """
**TOOL INSTRUCTION FOR THIS LEVEL:**
No specific node identifier available. Use the node_type to guide your analysis:
- If node_type is a class/interface: use analyze_inheritance_graph with a narrowed scope_path
- If node_type is a directory/module: use scan_files or extract_subgraph with the module path
- Focus on immediate children only, not the entire parent scope"""

    return f"""---

# CURRENT FOCUS (Drilldown Depth: {depth})

**SCOPE CONSTRAINT: You are analyzing a SPECIFIC NODE, not the entire parent scope.**

Current Path: `{path_str}`
Current Focus Node: `{current_focus_title}` (type: {current_focus.node_type})

**Critical Rules for This Level:**
1. **Limit your analysis** to the current focus (`{current_focus_title}`) and its direct sub-elements ONLY
2. **Do NOT** re-analyze, re-summarize, or include information about sibling nodes or parent components
3. **Treat the current focus as the "root"** - its direct children are what goes into `next_layer.nodes`
4. **Scope example:** If analyzing `deepdoc-parser > VisionParser`, your nodes should be methods/classes WITHIN VisionParser, NOT other parsers like `TCADPParser` or `TxtParser`

**In short:** Each drilldown level focuses ONE level deeper. No siblings, no parents—only children of the current focus.
{tool_guidance}"""


def format_component_request(
    request: ComponentDrilldownRequest,
) -> str:
    """Build the user-facing portion of the prompt with dynamic context and state injection.

    IMPORTANT: This injects progress state ("Phase 1: Scout") so the stateless LLM can
    track where it is in the Scout & Drill process. After tool results, the graph.py
    will inject progress to Phase 2 (Drill).
    """
    # Extract only essential fields from component_card (no duplicates)
    card = request.component_card
    compact_card = {
        "component_id": card.get("component_id"),
        "module_name": card.get("module_name"),
        "directory": card.get("directory"),
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

    # Build dynamic current focus section (changes based on breadcrumb depth)
    focus_section = _build_current_focus_section(
        request.breadcrumbs, card.get("module_name", "")
    )

    # Include focus section if at drilldown level, otherwise use standard separator
    if focus_section:
        focus_part = f"{focus_section}\n\n---"
    else:
        focus_part = "---"

    return f"""# COMPONENT CONTEXT
{formatted_payload}

{focus_part}

# PROGRESS STATE (Current Phase)

**YOU ARE NOW IN: PHASE 1 (SCOUT)**

**What to do:**
1. Look at the component's directory structure and name
2. Form a hypothesis about its design pattern (Pattern A/B/C)
3. Do NOT call tools yet - just analyze the context and decide which pattern it matches
4. Once you've identified the pattern, you will naturally transition to PHASE 2

**Examples for each pattern:**
- Pattern A (Registry): `deepdoc/parser/` (many _parser files) → Likely Plugin system
- Pattern B (Workflow): `agent/executor/` (names like run, flow, pipeline) → Likely Orchestration
- Pattern C (Interface): `api/routes/` (routes, handlers) → Likely Service boundary

After you call your first tool, the system will automatically advance you to PHASE 2 (DRILL).

---

# TASK
Analyze the component context and identify its pattern. Then call the appropriate tools.
Respond with pure JSON only (no markdown, no explanations outside JSON).
"""


__all__ = [
    "build_component_system_prompt",
    "format_component_request",
]
