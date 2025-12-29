"""Semantic extraction framework for bridging code structure to business meaning.

This module provides utilities for analyzing code components and extracting
semantic metadata that explains their business purpose, role, and significance.
"""

from typing import Any, Dict, List, Optional

from component_agent.schemas import (
    BusinessFlowPosition,
    RiskLevel,
    SemanticMetadata,
    SemanticRole,
)


def format_structural_findings(
    findings: Dict[str, Any],
    pattern: Optional[str] = None,
) -> str:
    """Format scout-phase structural findings for semantic extraction.

    Args:
        findings: Dictionary of structural analysis results from scout phase.
                Contains keys like 'class_names', 'method_names', 'inheritance', etc.
        pattern: Optional pattern name (A, B, or C) for pattern-specific formatting.

    Returns:
        Formatted string describing structural findings for LLM consumption.
    """
    lines = []

    # Class analysis
    if "class_names" in findings and findings["class_names"]:
        lines.append(f"Classes: {', '.join(findings['class_names'])}")

    # Method/function analysis
    if "public_methods" in findings and findings["public_methods"]:
        lines.append(f"Public methods: {', '.join(findings['public_methods'])}")

    if "private_methods" in findings and findings["private_methods"]:
        lines.append(f"Private methods: {', '.join(findings['private_methods'])}")

    # Dependencies
    if "dependencies" in findings and findings["dependencies"]:
        dep_list = ", ".join(findings["dependencies"][:5])
        lines.append(f"Dependencies: {dep_list}")

    # Inheritance hierarchy
    if "inheritance" in findings and findings["inheritance"]:
        lines.append(f"Inheritance: {findings['inheritance']}")

    # Interfaces/Protocols
    if "implements" in findings and findings["implements"]:
        lines.append(f"Implements: {', '.join(findings['implements'])}")

    # Key attributes
    if "attributes" in findings and findings["attributes"]:
        attrs = ", ".join(findings["attributes"][:5])
        lines.append(f"Key attributes: {attrs}")

    return "\n".join(lines)


def _build_pattern_a_semantic_prompt(
    component_name: str,
    structural_findings: str,
    context: str = "",
) -> str:
    """Build semantic extraction prompt for Pattern A (Registry/Factory).

    Pattern A typically involves:
    - Centralized management of components
    - Registration/discovery patterns
    - Factory or singleton behavior
    - Configuration management

    Args:
        component_name: Name of the component being analyzed.
        structural_findings: Formatted structural analysis from scout phase.
        context: Optional additional context about the component.

    Returns:
        LLM prompt for semantic extraction.
    """
    return f"""Analyze this registry/factory component and extract its business semantics:

Component: {component_name}

Structural findings:
{structural_findings}

{f"Context: {context}" if context else ""}

EXTRACT semantic metadata:
1. semantic_role: Choose ONE from [REPOSITORY, FACTORY, GATEWAY, MEDIATOR, ORCHESTRATOR]
2. business_context: 1-2 sentences explaining what this registry/factory does in business terms
3. business_significance: Why is this central management point important?
4. flow_position: Where does this fit? [ENTRY_POINT, PROCESSING, AGGREGATION, STORAGE]
5. risk_level: Assessment of business impact if this fails [CRITICAL, HIGH, MEDIUM, LOW]
6. dependencies_description: What systems depend on this registry?
7. impacted_workflows: List of workflows that depend on this component

RESPOND ONLY with valid JSON containing these 7 fields."""


def _build_pattern_b_semantic_prompt(
    component_name: str,
    structural_findings: str,
    context: str = "",
) -> str:
    """Build semantic extraction prompt for Pattern B (Workflow/Orchestrator).

    Pattern B typically involves:
    - Sequential execution flows
    - State management
    - Multi-step processes
    - Coordination logic

    Args:
        component_name: Name of the component being analyzed.
        structural_findings: Formatted structural analysis from scout phase.
        context: Optional additional context about the component.

    Returns:
        LLM prompt for semantic extraction.
    """
    return f"""Analyze this workflow/orchestrator component and extract its business semantics:

Component: {component_name}

Structural findings:
{structural_findings}

{f"Context: {context}" if context else ""}

EXTRACT semantic metadata:
1. semantic_role: Choose ONE from [ORCHESTRATOR, PROCESSOR, DISPATCHER, VALIDATOR, TRANSFORMER]
2. business_context: 1-2 sentences explaining what workflow/process this manages
3. business_significance: Why is this orchestration logic critical to the business?
4. flow_position: Where in the data flow? [ENTRY_POINT, VALIDATION, PROCESSING, TRANSFORMATION, OUTPUT]
5. risk_level: Impact if this orchestrator fails? [CRITICAL, HIGH, MEDIUM, LOW]
6. dependencies_description: What components does this orchestrator depend on?
7. impacted_workflows: List of business workflows this orchestrator manages

RESPOND ONLY with valid JSON containing these 7 fields."""


def _build_pattern_c_semantic_prompt(
    component_name: str,
    structural_findings: str,
    context: str = "",
) -> str:
    """Build semantic extraction prompt for Pattern C (API/Service Interface).

    Pattern C typically involves:
    - External-facing interfaces
    - API endpoints or service boundaries
    - Request/response handling
    - Protocol-specific logic

    Args:
        component_name: Name of the component being analyzed.
        structural_findings: Formatted structural analysis from scout phase.
        context: Optional additional context about the component.

    Returns:
        LLM prompt for semantic extraction.
    """
    return f"""Analyze this API/service interface component and extract its business semantics:

Component: {component_name}

Structural findings:
{structural_findings}

{f"Context: {context}" if context else ""}

EXTRACT semantic metadata:
1. semantic_role: Choose ONE from [GATEWAY, ADAPTER, MEDIATOR, PROCESSOR, SINK]
2. business_context: 1-2 sentences explaining what external interface this provides
3. business_significance: Why is this service boundary important for business operations?
4. flow_position: Where is this in the flow? [ENTRY_POINT, PROCESSING, OUTPUT, ERROR_HANDLING]
5. risk_level: Business impact if this interface is down? [CRITICAL, HIGH, MEDIUM, LOW]
6. dependencies_description: What backends does this API interface depend on?
7. impacted_workflows: List of workflows or external systems that depend on this API

RESPOND ONLY with valid JSON containing these 7 fields."""


def build_semantic_extraction_prompt(
    pattern: str,
    component_name: str,
    structural_findings: Dict[str, Any],
    class_name: Optional[str] = None,
    additional_context: str = "",
) -> str:
    """Build pattern-specific semantic extraction prompt for LLM.

    This function routes to appropriate pattern-specific prompt builder
    based on the detected architectural pattern.

    Args:
        pattern: Architectural pattern identifier ('A', 'B', or 'C')
        component_name: Name of the component being analyzed
        structural_findings: Dictionary of structural analysis results
        class_name: Optional specific class name being focused on
        additional_context: Optional additional context about the component

    Returns:
        LLM prompt string tailored to the pattern

    Raises:
        ValueError: If pattern is not recognized
    """
    # Format the structural findings
    formatted_findings = format_structural_findings(structural_findings, pattern)

    if class_name:
        context = f"Focusing on class: {class_name}\n{additional_context}".strip()
    else:
        context = additional_context

    pattern = pattern.upper() if pattern else ""

    if pattern == "A":
        return _build_pattern_a_semantic_prompt(
            component_name, formatted_findings, context
        )
    elif pattern == "B":
        return _build_pattern_b_semantic_prompt(
            component_name, formatted_findings, context
        )
    elif pattern == "C":
        return _build_pattern_c_semantic_prompt(
            component_name, formatted_findings, context
        )
    else:
        raise ValueError(
            f"Unknown pattern: {pattern}. Expected 'A', 'B', or 'C'"
        )


def parse_semantic_response(response: Dict[str, Any]) -> Optional[SemanticMetadata]:
    """Parse LLM response into SemanticMetadata instance.

    Args:
        response: Dictionary response from LLM with semantic fields.

    Returns:
        SemanticMetadata instance, or None if parsing fails.
    """
    if not response:
        return None

    try:
        # Convert string enums to actual enum values
        semantic_role = None
        if response.get("semantic_role"):
            role_str = response["semantic_role"].lower().replace(" ", "_")
            try:
                semantic_role = SemanticRole(role_str)
            except ValueError:
                pass

        flow_position = None
        if response.get("flow_position"):
            pos_str = response["flow_position"].lower().replace(" ", "_")
            try:
                flow_position = BusinessFlowPosition(pos_str)
            except ValueError:
                pass

        risk_level = None
        if response.get("risk_level"):
            risk_str = response["risk_level"].lower()
            try:
                risk_level = RiskLevel(risk_str)
            except ValueError:
                pass

        # Handle impacted workflows
        workflows = response.get("impacted_workflows", [])
        if isinstance(workflows, str):
            workflows = [w.strip() for w in workflows.split(",") if w.strip()]

        return SemanticMetadata(
            semantic_role=semantic_role,
            business_context=response.get("business_context"),
            business_significance=response.get("business_significance"),
            flow_position=flow_position,
            risk_level=risk_level,
            dependencies_description=response.get("dependencies_description"),
            impacted_workflows=workflows,
        )
    except Exception as e:
        # Log error but don't crash
        print(f"Error parsing semantic response: {e}")
        return None


# Semantic guidance constants for LLM instruction tuning


SEMANTIC_EXTRACTION_SYSTEM_MESSAGE = """You are an expert at bridging the gap between code structure and business meaning.
Given code analysis, you extract semantic metadata that explains:
- What role this component plays in business workflows
- Why it matters to the business
- What happens if it fails
- Which workflows depend on it

Be precise, concise, and think about business impact rather than technical details."""


SEMANTIC_CONFIDENCE_RULES = {
    "high": "Multiple lines of evidence from different analysis angles",
    "medium": "Clear structural patterns that suggest semantic role",
    "low": "Minimal evidence; semantic role inferred from naming only",
}


__all__ = [
    "format_structural_findings",
    "build_semantic_extraction_prompt",
    "parse_semantic_response",
    "SEMANTIC_EXTRACTION_SYSTEM_MESSAGE",
    "SEMANTIC_CONFIDENCE_RULES",
]
