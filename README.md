# Semantic Code Architecture Analysis Engine

## Overview

This is an LLM-powered codebase analysis system that bridges the **semantic gap** between technical code structure and business meaning. Rather than merely extracting syntactic artifacts (classes, functions, call graphs), the system derives business-level semantic metadata—architectural roles, data flow positions, business significance, and impact scope—enabling stakeholders to understand "what this code does" in organizational terms.

The system employs a **two-stage agentic architecture**: an Orchestration Agent that performs high-level component discovery and synthesis, followed by a Component Agent that implements fine-grained drilldown analysis using a Scout-Drill pattern to identify code architectural patterns and structure them into navigable hierarchies.

## Key Features

- **Dual-Stage Analysis**: Orchestration phase (system-wide component discovery) + Component phase (multi-level drilldown)
- **Pattern Recognition**: Autonomous detection of Registry/Plugin, Workflow/Orchestration, and API/Service architectural patterns
- **Semantic Extraction**: Extraction of 7 semantic dimensions (role, business context, significance, flow position, risk level, dependencies, impacted workflows) at all analysis levels
- **Stateful Navigation**: Redis-backed breadcrumb caching for seamless multi-level code exploration across stateless HTTP requests
- **Constraint-Based LLM Programming**: Multi-layer Pydantic validators enforcing cross-field consistency without relying on structured output
- **Tool-Driven Reasoning**: ReAct-based tool orchestration with 12+ specialized code analysis tools

## Architecture

### System-Level Data Flow

```
┌──────────────────────────────────────────────────────────────┐
│                     USER REQUEST                             │
│              POST /analyze {github_url}                      │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────┐
        │   Workspace Creation           │
        │  - Structural Indexing         │
        │  - Call Graph Construction     │
        │  - TreeSitter AST Parsing      │
        └────────────┬───────────────────┘
                     │
                     ▼
        ┌────────────────────────────────┐
        │  SSE Stream: /stream            │
        │  (IndexingProgress)             │
        └────────────┬───────────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
         ▼                       ▼
  ┌─────────────────┐  ┌─────────────────────┐
  │ Orchestration   │  │ Component Tools     │
  │ Agent (ReAct)   │  │ - extract_subgraph  │
  ├─────────────────┤  │ - analyze_inherit   │
  │ Tools:          │  │ - list_entry_pts   │
  │ • list_dirs     │  │ - find_paths       │
  │ • rank_nodes    │  │ - scan_files       │
  │ • extract_sg    │  └─────────────────────┘
  │ • find_paths    │
  │ • get_source    │
  └────────┬────────┘
           │
           ▼
  OrchestrationResponse
  ├─ system_overview
  ├─ layer_order
  ├─ component_cards [semantic_metadata]
  ├─ business_flow
  └─ deprioritised_signals
           │
           ▼ (Cache to plan.json)
           │
   ┌───────┴──────────────────────┐
   │                              │
   ▼                              ▼
GET /overview              User Clicks Node
   │                              │
   ▼                              ▼
Frontend Display      POST /drilldown
(Architecture Graph)     │
   ↑                     ├─ Load breadcrumbs (Redis)
   │                     │
   │                     ├─ Component Agent
   │                     │  ├─ Phase 1: SCOUT
   │                     │  │  (autonomous tool exploration)
   │                     │  │
   │                     │  └─ Phase 2: DRILL
   │                     │     (pattern-specific synthesis)
   │                     │
   │                     └─ ComponentDrilldownResponse
   │                        ├─ next_layer [NavigationNodes]
   │                        │  (each with semantic_metadata)
   │                        └─ cache_id (new breadcrumb state)
   │
   └─ Return cache_id to frontend
```

### Backend Agent Architecture (Detailed)

#### Stage 1: Orchestration Agent

```
Input: workspace_id, code_index

       ┌─────────────────────────────────────┐
       │  System Prompt (~8000 tokens)       │
       │  ├─ 3-phase approach guidance       │
       │  │  1. Discover: list_directory    │
       │  │  2. Deepen: rank_nodes, extract │
       │  │  3. Synthesize: identify components
       │  │                                  │
       │  ├─ Naming guidelines              │
       │  ├─ Landmark selection rules       │
       │  ├─ Layer concept definitions      │
       │  ├─ Semantic metadata extraction   │
       │  │  (7 fields: role, context,      │
       │  │   significance, position,       │
       │  │   risk_level, dependencies,     │
       │  │   impacted_workflows)          │
       │  └─ Validation checklist          │
       └─────────────────────────────────────┘
       │
       ▼
LangGraph StateGraph
│
├─ agent_node
│  └─ ChatModel with bound_tools
│     └─ call LLM with tool instructions
│
├─ tools_node
│  ├─ list_directory_components()
│  │  └─ returns { directory, top_nodes, importance }
│  │
│  ├─ rank_call_graph_nodes()
│  │  └─ PageRank over dependency graph
│  │
│  ├─ extract_subgraph()
│  │  └─ { node_id, neighbors, metadata }
│  │
│  ├─ find_paths()
│  │  └─ trace connections: start → end
│  │
│  └─ get_source_code()
│     └─ read implementation of node
│
├─ conditional_edge: should_continue()
│  ├─ if tool_calls in AIMessage → "tools"
│  └─ else → END
│
└─ loop: agent → tools → agent (recursion_limit=50)

Output: OrchestrationResponse
        ├─ system_overview {headline, key_workflows}
        ├─ layer_order []  # dynamic per project
        ├─ component_cards []
        │  └─ ComponentCard {
        │     id, module_name, business_signal,
        │     architecture_layer, confidence,
        │     leading_landmarks, objective,
        │     ⭐ semantic_metadata: SemanticMetadata {
        │        semantic_role (13 roles),
        │        business_context,
        │        business_significance,
        │        flow_position (8 positions),
        │        risk_level (CRITICAL|HIGH|MEDIUM|LOW),
        │        dependencies_description,
        │        impacted_workflows
        │     }
        │  }
        ├─ business_flow [{from, to, label}]
        └─ deprioritised_signals []

Cache: workspace.plan_path (JSON)
```

#### Stage 2: Component Agent (Scout & Drill)

```
Input: component_card, breadcrumbs, clicked_node, cache_id

Step 1: Load Breadcrumb State
        └─ Redis: drilldown:breadcrumbs:{workspace_id}:{cache_id}
           └─ append clicked_node → new breadcrumbs

Step 2: Format Component Request
        ├─ Compact component summary
        ├─ Breadcrumb trail (for context)
        └─ Dynamic focus section (depth-aware)
           └─ depth 0-1: "high-level patterns"
           └─ depth 2-3: "concrete components"
           └─ depth 3+: "implementation details"

Step 3: Phase 1 - SCOUT (Autonomous Exploration)
        │
        ├─ System Prompt Selection
        │  ├─ General Scout: pattern discovery via tools
        │  ├─ Class Inspector: class internals analysis
        │  └─ Focus-aware: dynamic based on breadcrumb depth
        │
        ├─ Human Prompt: format_component_request()
        │  └─ workspace_id, component_card, breadcrumbs context
        │
        ├─ Tool Calls (LLM autonomous decision)
        │  ├─ extract_subgraph(node_id, max_depth=1)
        │  ├─ analyze_inheritance_graph()
        │  ├─ find_paths(start, end)
        │  ├─ list_entry_points()
        │  └─ search_codebase() [if needed]
        │
        ├─ Iterations: max 50 (agent → tools → agent)
        │
        └─ Output Extraction: scout_pattern_identification JSON
           ├─ pattern_type: "A" | "B" | "C"
           │  └─ A = Registry/Plugin
           │  └─ B = Workflow/Orchestration
           │  └─ C = API/Service
           ├─ confidence: float [0, 1]
           ├─ tools_called: [string]
           └─ findings: string

Step 4: Phase 2 - DRILL (Structured Synthesis)
        │
        ├─ Pattern-Specific Prompt Template
        │  ├─ Pattern A Drill: plugin inheritance analysis
        │  ├─ Pattern B Drill: workflow execution flow
        │  ├─ Pattern C Drill: API endpoint categorization
        │  └─ Generic Drill: fallback (if pattern unrecognized)
        │
        ├─ Message Stack
        │  ├─ Scout's full conversation history
        │  │  (minus Scout's system prompt to prevent pollution)
        │  │
        │  └─ Drill System Prompt
        │     ├─ Pattern-specific analysis guidance
        │     ├─ Semantic metadata extraction rules
        │     │  └─ 7 required fields + pattern-specific hints
        │     ├─ CRITICAL validation rules
        │     │  ├─ action.kind must match node_type
        │     │  ├─ impacted_workflows ⊆ system_overview.key_workflows
        │     │  └─ semantic_role ∈ {13 predefined roles}
        │     └─ Output schema (JSON)
        │
        ├─ Model Invocation
        │  └─ with_structured_output(ComponentDrilldownResponse)
        │     └─ Pydantic validates response
        │
        └─ Output: ComponentDrilldownResponse
           ├─ component_id, agent_goal
           ├─ breadcrumbs (updated)
           └─ next_layer: NextLayerView {
              ├─ focus_label, rationale
              ├─ is_sequential: bool
              └─ nodes: [NavigationNode] {
                 ├─ node_key, title, node_type
                 ├─ description, action (kind, target_id, params)
                 ├─ ⭐ semantic_metadata: SemanticMetadata {
                 │  (same 7 fields as orchestration level)
                 │  role, context, significance,
                 │  position, risk_level, dependencies,
                 │  impacted_workflows
                 │ }
                 └─ business_narrative: str
              }
           }

Step 5: Response Formatting & Caching
        ├─ Enum conversion: semantic roles → strings
        ├─ Target ID validation (cross-db check)
        ├─ Cache new breadcrumbs → Redis
        │  └─ returns new cache_id
        └─ Return API response {cache_id, next_layer}
           └─ Frontend renders and provides new cache_id for next drill
```

### Key Data Structures

#### SemanticMetadata (7 Required Fields)

```python
class SemanticMetadata(BaseModel):
    # 1. Architectural Role (13 options)
    semantic_role: Literal[
        "gateway",      # Entry points (APIs, CLIs)
        "orchestrator", # Coordinates workflows
        "processor",    # Core business logic
        "repository",   # Data storage
        "adapter",      # Protocol/format translation
        "mediator",     # Bridges components
        "validator",    # Data/rule validation
        "transformer",  # Data conversion
        "aggregator",   # Multi-source merging
        "dispatcher",   # Work distribution
        "factory",      # Object creation
        "strategy",     # Pluggable implementations
        "sink"          # Data destination
    ]

    # 2. Business Context (1-2 sentences, non-technical)
    business_context: str
    # e.g., "Accepts HTTP requests and routes to handlers"

    # 3. Business Significance (why it matters)
    business_significance: str
    # e.g., "CRITICAL - All external access flows through this"

    # 4. Flow Position (8 options)
    flow_position: Literal[
        "ENTRY_POINT",
        "VALIDATION",
        "PROCESSING",
        "TRANSFORMATION",
        "AGGREGATION",
        "STORAGE",
        "OUTPUT",
        "ERROR_HANDLING"
    ]

    # 5. Risk Level (4 options)
    risk_level: Literal[
        "CRITICAL",  # System-wide outage
        "HIGH",      # Major workflows broken
        "MEDIUM",    # Some workflows broken
        "LOW"        # Minor features affected
    ]

    # 6. Dependencies Description
    dependencies_description: Optional[str]
    # e.g., "Depends on API Gateway and Database"

    # 7. Impacted Workflows (references system overview)
    impacted_workflows: List[str]
    # CONSTRAINT: Only from system_overview.key_workflows
```

## Technical Challenges & Solutions

### 1. Multi-Phase Message Coordination

**Challenge**: Scout and Drill phases must maintain coherent reasoning despite being separate LLM invocations.

**Solution**:
- Scout outputs structured `scout_pattern_identification` JSON
- Drill extracts pattern type and selects corresponding prompt template
- Scout's conversation history flows into Drill (with system prompt filtered to prevent prompt injection)
- Message stack protocol: `messages[3:-1]` removes Scout's system prompt

### 2. Constraint-Based Prompt Engineering

**Challenge**: LLM must generate outputs satisfying complex nested validation rules without structured output in Scout phase.

**Solution**:
- Orchestration prompt: ~8000 tokens of guidance covering discovery, synthesis, semantic extraction, and validation
- Component prompts: 4 Scout variations + 5 Drill variations, each with CRITICAL rules sections
- Pydantic validators enforce cross-field constraints (e.g., `action.kind` must match `node_type`)
- Validation failure triggers debugging feedback to identify LLM reasoning errors

### 3. Semantic Metadata Extraction

**Challenge**: Bridge technical code structure to business meaning without hallucination.

**Solution**:
- Predefined semantic role enumeration (13 roles) guides LLM choices
- Business flow position enumeration (8 positions) constrains reasoning space
- Risk level classification (4 levels) with explicit CRITICAL rules
- Pattern-specific semantic guidance in Drill prompts (e.g., Registry patterns → plugin role)
- Consistency enforced: identical semantic enums at orchestration and component levels

### 4. Stateless Drilldown Navigation

**Challenge**: Maintain multi-level navigation context across stateless HTTP requests.

**Solution**:
- Redis breadcrumb cache with UUID-based `cache_id`
- Workflow: load breadcrumbs → append clicked node → save new breadcrumbs → return new `cache_id`
- Dynamic focus section in Scout prompt changes based on `len(breadcrumbs)` (depth-aware analysis)
- Cache TTL=1 hour; graceful fallback if cache expires

### 5. Tool Integration & Autonomous Reasoning

**Challenge**: 12+ tools with different APIs must work seamlessly within ReAct loops.

**Solution**:
- Unified tool interface: all tools return `Dict[str, Any]` (JSON serializable)
- Tool descriptions in prompts guide LLM usage patterns
- Tools are stateless; composition handled by LLM (autonomous tool chaining)
- Scout may call same tool multiple times; results cached for Drill

### 6. JSON Extraction Without Structured Output

**Challenge**: Scout phase needs tool-calling (no structured output), but must emit pattern JSON.

**Solution**:
- Custom JSON extraction: search for `scout_pattern_identification` or first `{`, balance braces, parse
- Graceful degradation: if JSON extraction fails, use generic Drill prompt
- Handles escaped quotes, nested structures, and JSON across paragraphs

## Project Structure

```
ArchAI/
├── backend/
│   ├── api/
│   │   ├── routes/workspaces.py      # API endpoints (stream, overview, drilldown)
│   │   └── schemas.py                 # Request/response DTOs
│   │
│   ├── orchestration_agent/
│   │   ├── graph.py                   # LangGraph ReAct workflow
│   │   ├── llm.py                     # LLM provider abstraction
│   │   ├── prompt.py                  # Prompt templates (8000+ tokens)
│   │   ├── schemas.py                 # OrchestrationResponse, ComponentCard
│   │   └── toolkit.py                 # 5 discovery tools
│   │
│   ├── component_agent/
│   │   ├── graph.py                   # Scout-Drill two-phase workflow
│   │   ├── llm.py                     # LLM configuration
│   │   ├── prompt.py                  # 4 Scout + 5 Drill templates
│   │   ├── schemas.py                 # NavigationNode, SemanticMetadata
│   │   ├── semantic_analyzer.py       # Semantic extraction guidance
│   │   ├── token_tracker.py           # Token usage tracking
│   │   └── toolkit.py                 # 12+ code analysis tools
│   │
│   ├── drilldown_cache.py             # Redis breadcrumb management
│   ├── workspace.py                   # Workspace abstraction
│   ├── llm_logger.py                  # LLM invocation logging
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── app/                       # Next.js app router
│   │   ├── components/
│   │   │   └── workspace/
│   │   │       ├── architecture-graph.tsx     # Component visualization
│   │   │       ├── semantic-panel.tsx         # Semantic metadata display
│   │   │       ├── semantic-badge.tsx         # Metadata visual indicator
│   │   │       └── business-narrative.tsx     # Narrative display
│   │   │
│   │   └── lib/
│   │       ├── api.ts                 # API client & types
│   │       └── type-guards.ts         # Type utilities
│   │
│   └── package.json
│
└── README.md (this file)
```

## Configuration

### Environment Variables

```bash
# LLM Provider
ORCHESTRATION_LLM_PROVIDER=gemini|openai        # default: gemini
ORCHESTRATION_GEMINI_API_KEY=...
ORCHESTRATION_OPENAI_API_KEY=...
ORCHESTRATION_OPENAI_MODEL=gpt-4o-mini          # if using OpenAI
ORCHESTRATION_GEMINI_MODEL=gemini-2.5-pro       # if using Gemini

# Component Agent (inherits from orchestration, can override)
COMPONENT_AGENT_LLM_PROVIDER=...
COMPONENT_AGENT_GEMINI_API_KEY=...
COMPONENT_AGENT_OPENAI_API_KEY=...

# Database & Caching
STRUCTURAL_SCAFFOLD_DB_URL=postgresql://...     # Workspace index storage
REDIS_URL=redis://localhost:6379                # Breadcrumb cache

# Debugging
DEBUG=false                                      # Set to true for raw log output
```

## LLM Integration

**Supported Providers**:
- OpenAI: GPT-4o-mini (default), GPT-4o
- Google Gemini: Gemini 2.5-pro (default), Gemini 2.0-flash

**Temperature Settings**:
- Orchestration: 0.2 (exploratory but deterministic)
- Component Scout: 0.0 (precise pattern recognition)
- Component Drill: 0.0 (consistent synthesis)

**Token Tracking**: Built-in token usage tracking via `TokenTracker` module.

## Design Principles

### 1. Rule-Based LLM Constraints

Rather than depending on LLM adherence to format specifications, the system uses **Pydantic validators as constraint enforcement mechanisms**. Invalid outputs are caught at the schema level, not at parsing time, enabling precise error feedback.

### 2. Prompt Engineering as First-Class Concern

Prompt construction is modularized and versioned. Pattern-specific variations are explicit. CRITICAL rules are textual constraints, not mere suggestions.

### 3. Semantic Consistency Across Stages

Orchestration and Component agents use identical semantic role/position/risk enumerations. This ensures business-level metadata is coherent across analysis levels.

### 4. Tool-Driven Reasoning

Tools are not mere utilities; they are the primary reasoning substrate. LLM autonomously decides tool combinations. Scout's tool results directly influence Drill's synthesis, avoiding hallucination.

### 5. Stateless HTTP with Stateful Reasoning

Drilldown state is managed via Redis cache IDs. Each HTTP request is logically self-contained but semantically continuous with prior requests.

## Performance Characteristics

- **Orchestration**: ~30-60 seconds (depending on codebase size and LLM provider)
  - Includes 3-10 ReAct iterations
  - Typical tool calls: 5-15 per iteration

- **First Drilldown**: ~10-20 seconds
  - Scout phase: 2-5 iterations
  - Drill phase: 1 structured output

- **Subsequent Drilldowns**: ~10-20 seconds
  - Breadcrumb caching reduces context overhead

- **Caching**: Plan.json cached indefinitely; breadcrumbs cached 1 hour

## Future Work

1. **Evaluation Framework**: Automated + human evaluation of semantic metadata accuracy
2. **Caching Optimization**: Persistent semantic metadata cache to reduce recomputation
3. **Pattern Library**: Extensible pattern definitions for domain-specific architectures
4. **Real-time Collaboration**: Multi-user concurrent drilldown with shared cache
5. **Export Formats**: Architecture documentation generation (Markdown, PlantUML, C4 diagrams)

**Last Updated**: December 2025
