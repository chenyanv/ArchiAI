"""Data contracts for the orchestration agent."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from typing_extensions import Literal

from component_agent.schemas import SemanticMetadata


# Architecture layer is now dynamic - LLM decides the categories based on project type
# Examples: "core", "api", "commands", "parser", "models", "utils", etc.


ConfidenceLevel = Literal["high", "medium", "low"]


class LandmarkRef(BaseModel):
    """Reference to a structural landmark."""
    node_id: Optional[str] = Field(default=None, description="Graph node ID")
    symbol: Optional[str] = Field(default=None, description="Qualified symbol name")
    summary: Optional[str] = Field(default=None, description="Brief description")


class ComponentCard(BaseModel):
    """A business component identified in the codebase."""
    component_id: str = Field(..., description="Kebab-case identifier")
    module_name: str = Field(..., description="Human-readable name based on directory/module")
    directory: Optional[str] = Field(
        default=None,
        description="The directory path this component corresponds to"
    )
    business_signal: str = Field(
        ...,
        description="What business capability this enables"
    )
    architecture_layer: str = Field(
        default="core",
        description="Must match one of the layer_order values. Determines vertical position in visualization."
    )
    rank: int = Field(
        default=0,
        description="Layout rank computed from layer_order (0 = top layer, higher = lower in visualization)"
    )
    leading_landmarks: List[LandmarkRef] = Field(
        default_factory=list,
        description="Key structural landmarks in this component"
    )
    objective: List[str] = Field(
        default_factory=list,
        description="Investigation questions for deeper analysis"
    )
    confidence: ConfidenceLevel = Field(
        default="medium",
        description="Confidence level in this component identification"
    )
    semantic_metadata: Optional[SemanticMetadata] = Field(
        default=None,
        description="Business semantic information for this component (role, significance, workflows, etc.)"
    )


class ComponentEdge(BaseModel):
    """A directed relationship between two components."""
    from_component: str = Field(..., description="Source component_id (the caller/requester)")
    to_component: str = Field(..., description="Target component_id (the callee/provider)")
    label: Optional[str] = Field(default=None, description="Relationship type, e.g. 'calls', 'uses', 'depends on'")


class DeprioritisedSignal(BaseModel):
    """A signal that was identified but deprioritised."""
    signal: str = Field(..., description="The signal identifier or symbol")
    reason: str = Field(..., description="Why this was deprioritised")


class SystemOverview(BaseModel):
    """High-level overview of the analyzed system."""
    headline: str = Field(..., description="One sentence describing what this system does")
    key_workflows: List[str] = Field(
        default_factory=list,
        description="Main business workflows in the system"
    )


class TokenMetrics(BaseModel):
    """Token usage and cost tracking."""
    prompt_tokens: int = Field(default=0, description="Number of prompt tokens used")
    completion_tokens: int = Field(default=0, description="Number of completion tokens used")
    total_tokens: int = Field(default=0, description="Total tokens used")
    estimated_cost: float = Field(default=0.0, description="Estimated cost in USD")


class OrchestrationResponse(BaseModel):
    """Complete response from the orchestration agent."""
    system_overview: SystemOverview = Field(
        ...,
        description="High-level system overview"
    )
    layer_order: List[str] = Field(
        default_factory=list,
        description="Ordered list of architecture layers from top to bottom (e.g. ['interface', 'orchestration', 'core', 'data'])"
    )
    component_cards: List[ComponentCard] = Field(
        default_factory=list,
        description="Identified business components ordered by importance"
    )
    business_flow: List[ComponentEdge] = Field(
        default_factory=list,
        description="Connection arrows between components (does not affect layout)"
    )
    deprioritised_signals: List[DeprioritisedSignal] = Field(
        default_factory=list,
        description="Signals that were identified but not prioritized"
    )
    token_metrics: Optional[TokenMetrics] = Field(
        default=None,
        description="Token usage metrics from the orchestration phase"
    )


__all__ = [
    "ConfidenceLevel",
    "LandmarkRef",
    "ComponentCard",
    "ComponentEdge",
    "DeprioritisedSignal",
    "SystemOverview",
    "TokenMetrics",
    "OrchestrationResponse",
]
