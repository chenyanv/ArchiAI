# Component Sub-Agent Flow (Nov 10)

This document captures the full drilldown flow that now powers the "component → sub-component" navigation loop described on Nov 10.

## 1. End-to-End Journey

1. **Launch the unified CLI**:
   ```bash
   python -m archai_cli --database-url postgresql+psycopg://...
   ```
   - This single command performs orchestration, prints the component list, prompts for a selection, then automatically hands off to the component sub-agent.
   - Use `--plan-path` to change where the orchestration JSON is written (default `results/orchestration_plan.json`).
   - Use `--component-id <id>` to skip the selection prompt and jump straight into a known component.
2. **Display components**: the CLI prints every card with `component_id`, `module_name`, and objectives so the user can pick by index or id.
3. **Sub-agent session**: after the user (or `--component-id`) chooses a card, the CLI keeps the breadcrumbs in memory and repeatedly calls the component agent as the user drills deeper.
4. **Agent emits the next layer** (3–6 nodes). The CLI renders them as buttons/options. Each node specifies the follow-up action:
   - `component_drilldown` → append the node to breadcrumbs and call the agent again.
   - `inspect_source` → fetch code via `tools.get_source_code` and display it inline.
   - `inspect_node` → show node metadata (e.g. `get_node_details`).
   - `inspect_tool` → run the named tool and show raw output (e.g. "list_core_models with directories=["api/db"]").
   - `graph_overlay` → render the requested nodes/edges in your frontend graph view.
5. **User picks another node** → CLI forwards the breadcrumb trail back to the agent (JSON array) and repeats automatically. The agent updates its `agent_goal` and chooses the next breakdown (Parser example: PDF/Markdown/Markdown-on-canvas; Agent example: tools/prompts/services; File-level example: functions + direct source buttons).

## 2. Agent Architecture

- **Engine**: LangGraph ReAct agent (`langgraph>=0.2.40`).
- **LLM abstraction**: `component_agent.llm.build_component_chat_model` (OpenAI or Gemini; respects `COMPONENT_AGENT_*` env vars with fallbacks to the orchestration env vars).
- **Tools**: all structural tools are exposed via `component_agent.toolkit.DEFAULT_SUBAGENT_TOOLS` (PageRank, relatives, call-graph context, entry points, models, source code, …). The prompt automatically lists these tools with descriptions so the model knows what it can call.
- **Prompt**: `component_agent.prompt` enforces that the agent
  1. Sets its own `agent_goal`.
  2. Uses tools when it needs evidence (passing `database_url` through when provided).
  3. Always returns JSON that matches `ComponentDrilldownResponse` (see §3).
- **Graph**: `component_agent.graph` wires the chat model + `ToolNode` inside a LangGraph `StateGraph`. The helper `run_component_agent()` handles prompting, execution, and JSON parsing.

## 3. Data Contracts

### Request (`ComponentDrilldownRequest`)

```json
{
  "component_card": { ... },
  "breadcrumbs": [
    {
      "node_key": "document-knowledge-base-management",
      "title": "Knowledge Base Service",
      "node_type": "capability",
      "target_id": "document-knowledge-base-management",
      "metadata": {"focus": "ingestion"}
    }
  ],
  "subagent_payload": {
    "objective": [
      "Trace the data flow from upload to chunk storage",
      "Identify which API calls chunk_app.py::set"
    ]
  },
  "database_url": "postgresql+psycopg://..."
}
```

- `breadcrumbs` tell the agent where the user currently is. The CLI simply keeps appending the node the user clicked.
- `database_url` flows into every tool invocation when provided, keeping results scoped to the right codebase.

### Response (`ComponentDrilldownResponse`)

```json
{
  "component_id": "document-knowledge-base-management",
  "agent_goal": "Map how document ingestion fans out into chunk pipelines before handing control to retrieval services.",
  "breadcrumbs": [... updated trail ...],
  "next_layer": {
    "focus_label": "Knowledge Base Service",
    "focus_kind": "capability",
    "rationale": "Split by ingestion vs enrichment vs serving so the user can follow the lifecycle.",
    "nodes": [
      {
        "node_key": "document-upload-api",
        "title": "Document Upload API",
        "node_type": "workflow",
        "description": "FastAPI routes that accept files and dispatch them to ingestion queues.",
        "action": {
          "kind": "component_drilldown",
          "target_id": "document-upload-api",
          "parameters": {"entry_point_node": "python::api/apps/kb_app.py::knowledge_graph"}
        },
        "evidence": [
          {
            "source_type": "entry_point",
            "node_id": "python::api/apps/kb_app.py::knowledge_graph",
            "route": "/<kb_id>/knowledge_graph",
            "rationale": "Primary ingestion route that seeds the knowledge graph."
          }
        ],
        "score": 0.32
      },
      {
        "node_key": "chunking-hotspot",
        "title": "Chunk Creation Hotspot",
        "node_type": "function",
        "description": "`chunk_app.py::set` orchestrates chunk batching and persistence; inspect source directly.",
        "action": {
          "kind": "inspect_source",
          "target_id": "python::api/apps/chunk_app.py::set",
          "parameters": {"file_path": "api/apps/chunk_app.py"}
        },
        "evidence": [
          {"source_type": "landmark", "node_id": "python::api/apps/chunk_app.py::set"}
        ]
      }
    ]
  },
  "notes": [
    "Risk: chunk_app.py::set dominates PageRank, so treat it as a potential bottleneck."
  ],
  "raw_response": "... exact JSON string from the agent ..."
}
```

The CLI renders `next_layer.nodes` as buttons. When a user clicks one, feed the node back as a breadcrumb entry and call the agent again.

## 4. CLI Contract Summary

| Action kind | UI behaviour |
|-------------|--------------|
| `component_drilldown` | Append node to breadcrumbs and rerun the agent (lets the agent redefine the next taxonomy). |
| `inspect_source` | Call `tools.get_source_code` with `target_id` and show the code snippet (use `start_line`/`end_line`). |
| `inspect_node` | Call `tools.get_node_details`/`get_call_graph_context` for the provided `target_id`; show the payload inline. |
| `inspect_tool` | Execute the requested tool with `action.parameters`; render raw JSON. |
| `graph_overlay` | Render a graph (use your frontend). `parameters` will contain `nodes`/`edges` the agent wants to highlight. |

## 5. Running Locally

### Option A: Single command

```bash
python -m archai_cli --database-url postgresql+psycopg://archai:archai@localhost:55432/structural_scaffolding
```

Add `--debug-agent` to surface every LLM call and tool invocation:

```bash
python -m archai_cli --database-url ... --debug-agent
```

This runs orchestration, writes `results/orchestration_plan.json`, prints the component list, and launches the interactive drilldown loop.

### Option B: Manual control (legacy flow)

```bash
python scripts/run_orchestration_agent.py > results/orchestration_plan.json
jq '.component_cards[].component_id' results/orchestration_plan.json
python -m component_agent.runner document-knowledge-base-management \
  --plan-path results/orchestration_plan.json \
  --database-url postgresql+psycopg://archai:archai@localhost:55432/structural_scaffolding
```

Both approaches return a validated `ComponentDrilldownResponse`, which the CLI renders immediately. Because we rely on LangGraph's `ToolNode`, the agent already knows how to call any structural tool autonomously; no extra orchestration logic is required downstream.
