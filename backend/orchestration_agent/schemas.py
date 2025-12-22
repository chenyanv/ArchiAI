"""Data contracts for the orchestration agent."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from typing_extensions import Literal


# Architecture layer is now dynamic - LLM decides the categories based on project type
# Examples: "core", "api", "commands", "parser", "models", "utils", etc.


ConfidenceLevel = Literal["high", "medium", "low"]


class EntryPointRef(BaseModel):
    """Reference to an HTTP entry point."""
    node_id: Optional[str] = Field(default=None, description="Graph node ID")
    route: Optional[str] = Field(default=None, description="HTTP route path")
    handler: Optional[str] = Field(default=None, description="Handler function name")


class LandmarkRef(BaseModel):
    """Reference to a structural landmark."""
    node_id: Optional[str] = Field(default=None, description="Graph node ID")
    symbol: Optional[str] = Field(default=None, description="Qualified symbol name")
    summary: Optional[str] = Field(default=None, description="Brief description")


class CoreModelRef(BaseModel):
    """Reference to a core data model."""
    node_id: Optional[str] = Field(default=None, description="Graph node ID")
    model: Optional[str] = Field(default=None, description="Model class name")


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
        description="Component category (LLM decides based on project type, e.g. 'core', 'api', 'commands', 'parser', 'models', 'utils')"
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


class OrchestrationResponse(BaseModel):
    """Complete response from the orchestration agent."""
    system_overview: SystemOverview = Field(
        ...,
        description="High-level system overview"
    )
    component_cards: List[ComponentCard] = Field(
        default_factory=list,
        description="Identified business components ordered by importance"
    )
    deprioritised_signals: List[DeprioritisedSignal] = Field(
        default_factory=list,
        description="Signals that were identified but not prioritized"
    )


__all__ = [
    "ConfidenceLevel",
    "EntryPointRef",
    "LandmarkRef",
    "CoreModelRef",
    "ComponentCard",
    "DeprioritisedSignal",
    "SystemOverview",
    "OrchestrationResponse",
]
