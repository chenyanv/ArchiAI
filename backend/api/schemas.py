"""API request/response schemas."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# === Semantic Metadata (for bridging code structure to business meaning) ===

class SemanticMetadataDTO(BaseModel):
    """Business semantic information extracted from code analysis."""
    semantic_role: Optional[str] = Field(
        default=None,
        description="Role in business workflows (e.g., 'gateway', 'processor', 'validator')"
    )
    business_context: Optional[str] = Field(
        default=None,
        description="Explanation of what this component does in business terms"
    )
    business_significance: Optional[str] = Field(
        default=None,
        description="Why this component matters to the business"
    )
    flow_position: Optional[str] = Field(
        default=None,
        description="Position in business data/control flows"
    )
    risk_level: Optional[str] = Field(
        default=None,
        description="Business impact if this component fails"
    )
    dependencies_description: Optional[str] = Field(
        default=None,
        description="Critical dependencies this component relies on"
    )
    impacted_workflows: List[str] = Field(
        default_factory=list,
        description="Business workflows affected by this component"
    )


# === Token Metrics ===

class TokenMetrics(BaseModel):
    """Token usage and cost tracking."""
    prompt_tokens: int = Field(default=0, description="Number of prompt tokens used")
    completion_tokens: int = Field(default=0, description="Number of completion tokens used")
    total_tokens: int = Field(default=0, description="Total tokens used")
    estimated_cost: float = Field(default=0.0, description="Estimated cost in USD")


# === Analyze ===

class AnalyzeRequest(BaseModel):
    github_url: str = Field(..., description="GitHub repository URL")


class AnalyzeResponse(BaseModel):
    workspace_id: str


# === SSE Events ===

class SSEEvent(BaseModel):
    status: str
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


# === Workspace Overview ===

class SystemOverviewDTO(BaseModel):
    headline: str
    key_workflows: List[str] = []


class ComponentDTO(BaseModel):
    component_id: str
    module_name: str
    business_signal: str
    confidence: str
    objective: List[str] = []
    leading_landmarks: List[Dict[str, Any]] = []
    semantic_metadata: Optional[SemanticMetadataDTO] = Field(
        default=None,
        description="Business semantic information for this component"
    )


class WorkspaceOverviewResponse(BaseModel):
    workspace_id: str
    system_overview: SystemOverviewDTO
    components: List[ComponentDTO]
    token_metrics: Optional[TokenMetrics] = Field(
        default=None,
        description="Token usage metrics from orchestration phase"
    )


# === Drilldown ===

class DrilldownRequest(BaseModel):
    breadcrumbs: List[Dict[str, Any]] = Field(default_factory=list)
    cache_id: Optional[str] = Field(
        default=None,
        description="Cache ID for loaded breadcrumbs (if continuing drilldown)"
    )
    component_card: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Component card from orchestration (required for first drilldown)"
    )
    clicked_node: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Node that user clicked on for drilldown (adds to breadcrumb trail)"
    )


class NavigationNodeDTO(BaseModel):
    node_key: str
    title: str
    node_type: str
    description: str
    action_kind: str
    target_id: Optional[str] = None
    action_parameters: Optional[Dict[str, Any]] = None
    sequence_order: Optional[int] = None
    semantic_metadata: Optional[SemanticMetadataDTO] = Field(
        default=None,
        description="Business semantic information about this node"
    )
    business_narrative: Optional[str] = Field(
        default=None,
        description="Story-format explanation of this node's role in business context"
    )


class DrilldownResponse(BaseModel):
    component_id: str
    agent_goal: str
    focus_label: str
    rationale: str
    is_sequential: bool
    nodes: List[NavigationNodeDTO]
    cache_id: str  # Breadcrumb cache ID for next drilldown
    token_metrics: Optional[TokenMetrics] = Field(
        default=None,
        description="Token usage metrics from this drilldown operation"
    )


# === Source Code ===

class SourceCodeResponse(BaseModel):
    node_id: str
    code: str
    file_path: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
