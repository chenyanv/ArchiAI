"""API request/response schemas."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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


class WorkspaceOverviewResponse(BaseModel):
    workspace_id: str
    system_overview: SystemOverviewDTO
    components: List[ComponentDTO]


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


class DrilldownResponse(BaseModel):
    component_id: str
    agent_goal: str
    focus_label: str
    rationale: str
    is_sequential: bool
    nodes: List[NavigationNodeDTO]
    cache_id: str  # Breadcrumb cache ID for next drilldown


# === Source Code ===

class SourceCodeResponse(BaseModel):
    node_id: str
    code: str
    file_path: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
