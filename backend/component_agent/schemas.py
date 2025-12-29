"""Data contracts for the hierarchical component sub-agent."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Literal


# Node types that support component_drilldown action (can be drilled into)
DRILLABLE_NODE_TYPES = {"class", "workflow", "service", "category", "capability"}


NavigationActionKind = Literal[
    "component_drilldown",
    "inspect_source",
    "inspect_node",
    "inspect_tool",
    "graph_overlay",
]


NavigationNodeType = Literal[
    "capability",
    "category",
    "workflow",
    "pipeline",
    "agent",
    "file",
    "function",
    "class",
    "model",
    "dataset",
    "prompt",
    "tool",
    "service",
    "graph",
    "source",
]


EvidenceSourceType = Literal[
    "landmark",
    "entry_point",
    "model",
    "file",
    "tool_result",
    "custom",
]


# Semantic metadata enums for bridging code structure to business meaning


class SemanticRole(str, Enum):
    """Classification of what role this component plays in business workflows."""
    GATEWAY = "gateway"
    PROCESSOR = "processor"
    SINK = "sink"
    ORCHESTRATOR = "orchestrator"
    VALIDATOR = "validator"
    TRANSFORMER = "transformer"
    AGGREGATOR = "aggregator"
    DISPATCHER = "dispatcher"
    ADAPTER = "adapter"
    MEDIATOR = "mediator"
    REPOSITORY = "repository"
    FACTORY = "factory"
    STRATEGY = "strategy"


class BusinessFlowPosition(str, Enum):
    """Position of this component within typical business data/control flows."""
    ENTRY_POINT = "entry_point"
    VALIDATION = "validation"
    PROCESSING = "processing"
    TRANSFORMATION = "transformation"
    AGGREGATION = "aggregation"
    STORAGE = "storage"
    OUTPUT = "output"
    ERROR_HANDLING = "error_handling"


class RiskLevel(str, Enum):
    """Business-relevant risk classification for this component."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SemanticMetadata(BaseModel):
    """Business semantic information extracted from code structure and context."""
    semantic_role: Optional[SemanticRole] = Field(
        default=None,
        description="What role this component plays in business workflows.",
    )
    business_context: Optional[str] = Field(
        default=None,
        description="1-2 sentences explaining what this component does in business terms.",
    )
    business_significance: Optional[str] = Field(
        default=None,
        description="Why this component matters to the business or system.",
    )
    flow_position: Optional[BusinessFlowPosition] = Field(
        default=None,
        description="Position of this component within typical business flows.",
    )
    risk_level: Optional[RiskLevel] = Field(
        default=None,
        description="Business-relevant risk classification.",
    )
    dependencies_description: Optional[str] = Field(
        default=None,
        description="Brief description of critical dependencies this component relies on.",
    )
    impacted_workflows: List[str] = Field(
        default_factory=list,
        description="List of business workflows that depend on or are affected by this component.",
    )


class EvidenceItem(BaseModel):
    source_type: EvidenceSourceType = Field(..., description="Class of evidence backing this node.")
    node_id: Optional[str] = Field(
        default=None,
        description="Structural graph node identifier when applicable.",
    )
    label: Optional[str] = Field(default=None, description="Human label for the evidence item.")
    route: Optional[str] = Field(
        default=None,
        description="HTTP route when the evidence references an entry point.",
    )
    file_path: Optional[str] = Field(
        default=None,
        description="File path when the evidence references source code.",
    )
    rationale: Optional[str] = Field(
        default=None,
        description="Short sentence describing why this evidence matters.",
    )


class NavigationAction(BaseModel):
    kind: NavigationActionKind = Field(
        ...,
        description=(
            "Indicates how the CLI should respond when the user selects this node."
        ),
    )
    target_id: Optional[str] = Field(
        default=None,
        description="Identifier of the downstream target (component_id or node_id).",
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque metadata the CLI can pass back when resolving the selection.",
    )


class NavigationNode(BaseModel):
    node_key: str = Field(
        ...,
        description="Unique kebab-case identifier for this node within the current layer.",
    )
    title: str = Field(..., description="Label shown to the user.")
    node_type: NavigationNodeType = Field(..., description="Semantic type of the node.")
    description: str = Field(..., description="1-2 sentences describing what this node represents.")
    action: NavigationAction = Field(
        ..., description="Action metadata exposed to the CLI when this node is clicked."
    )
    evidence: List[EvidenceItem] = Field(
        default_factory=list,
        description="Evidence list tying this node back to structural signals.",
    )
    score: Optional[float] = Field(
        default=None,
        description="Optional relative importance score between 0 and 1.",
    )
    sequence_order: Optional[int] = Field(
        default=None,
        description="Position in workflow sequence (0-indexed). None if not part of a sequential flow.",
    )
    semantic_metadata: Optional[SemanticMetadata] = Field(
        default=None,
        description="Business semantic information about this node.",
    )
    business_narrative: Optional[str] = Field(
        default=None,
        description="Story-format narrative explaining this component's role in business context.",
    )

    @field_validator("action")
    @classmethod
    def validate_action_kind(cls, action: NavigationAction, info) -> NavigationAction:
        """Enforce that action.kind matches node_type drillability requirements."""
        node_type = info.data.get("node_type")
        if node_type in DRILLABLE_NODE_TYPES:
            if action.kind != "component_drilldown":
                raise ValueError(
                    f"node_type='{node_type}' must have action.kind='component_drilldown', "
                    f"got '{action.kind}'"
                )
        else:
            if action.kind != "inspect_source":
                raise ValueError(
                    f"node_type='{node_type}' must have action.kind='inspect_source', "
                    f"got '{action.kind}'"
                )
        return action


class NextLayerView(BaseModel):
    focus_label: str = Field(..., description="Human readable label of the current focus.")
    focus_kind: str = Field(..., description="What the agent considers this focus to be.")
    rationale: str = Field(..., description="Why the agent picked the current breakdown strategy.")
    nodes: List[NavigationNode] = Field(
        ..., description="Proposed next-layer nodes presented to the user.")
    workflow_narrative: Optional[str] = Field(
        default=None,
        description="1-3 sentence description of how these nodes form a workflow or process.",
    )
    is_sequential: bool = Field(
        default=False,
        description="True if nodes should be displayed as a sequential flow diagram.",
    )

    @model_validator(mode="after")
    def _validate_nodes(self) -> "NextLayerView":
        if not self.nodes:
            raise ValueError("NextLayerView requires at least one navigation node.")
        return self


class NavigationBreadcrumb(BaseModel):
    node_key: str = Field(..., description="Identifier provided by a previous navigation node.")
    title: str = Field(..., description="Label for the breadcrumb.")
    node_type: str = Field(..., description="The semantic type at that step.")
    target_id: Optional[str] = Field(
        default=None,
        description="Identifier of the downstream item associated with the breadcrumb.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque dictionary forwarded back to the agent for extra context.",
    )


class ComponentDrilldownRequest(BaseModel):
    component_card: Mapping[str, Any] = Field(
        ..., description="Raw component card produced by the orchestration agent."
    )
    breadcrumbs: List[NavigationBreadcrumb] = Field(
        default_factory=list,
        description="Path representing the user's drilldown so far (root-first).",
    )
    subagent_payload: Optional[Mapping[str, Any]] = Field(
        default=None,
        description="Optional directives from orchestration about investigative goals.",
    )
    workspace_id: str = Field(
        ..., description="Unique identifier for the workspace being analyzed."
    )
    database_url: Optional[str] = Field(
        default=None,
        description="Optional override for the structural scaffolding database URL.",
    )

    def current_focus(self) -> Optional[NavigationBreadcrumb]:
        if not self.breadcrumbs:
            return None
        return self.breadcrumbs[-1]


class ComponentDrilldownResponse(BaseModel):
    component_id: str = Field(..., description="Identifier of the component being analysed.")
    agent_goal: str = Field(..., description="Goal statement authored by the sub-agent for this hop.")
    breadcrumbs: List[NavigationBreadcrumb] = Field(
        default_factory=list,
        description="Updated breadcrumb trail including the current focus node.",
    )
    next_layer: NextLayerView = Field(
        ..., description="Structured representation of the next selectable nodes."
    )
    notes: List[str] = Field(
        default_factory=list,
        description="Short diagnostic or investigative notes for the user.",
    )
    raw_response: Optional[str] = Field(
        default=None,
        description="Raw JSON string returned by the LLM for debugging.",
    )


def coerce_subagent_payload(component_card: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalise orchestration output so the sub-agent always receives objectives."""

    payload: Dict[str, Any] = {}
    raw_payload = component_card.get("subagent_payload")
    if isinstance(raw_payload, Mapping):
        payload.update(raw_payload)
    objectives = component_card.get("objective")
    if isinstance(objectives, Sequence):
        cleaned = [
            item.strip()
            for item in objectives
            if isinstance(item, str) and item.strip()
        ]
        if cleaned and "objective" not in payload:
            payload["objective"] = cleaned
    return payload or None


__all__ = [
    "DRILLABLE_NODE_TYPES",
    "NavigationActionKind",
    "NavigationNodeType",
    "EvidenceSourceType",
    "SemanticRole",
    "BusinessFlowPosition",
    "RiskLevel",
    "EvidenceItem",
    "SemanticMetadata",
    "NavigationAction",
    "NavigationNode",
    "NextLayerView",
    "NavigationBreadcrumb",
    "ComponentDrilldownRequest",
    "ComponentDrilldownResponse",
    "coerce_subagent_payload",
]
