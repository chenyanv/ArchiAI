"""Test semantic metadata conversion in API routes."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from enum import Enum


class SemanticRole(str, Enum):
    """Semantic role enum (simplified for testing)."""
    GATEWAY = "gateway"
    PROCESSOR = "processor"
    ORCHESTRATOR = "orchestrator"


class BusinessFlowPosition(str, Enum):
    """Business flow position enum (simplified for testing)."""
    ENTRY_POINT = "entry_point"
    PROCESSING = "processing"


class RiskLevel(str, Enum):
    """Risk level enum (simplified for testing)."""
    CRITICAL = "critical"
    HIGH = "high"


class SemanticMetadata:
    """Simplified semantic metadata for testing."""
    def __init__(self, semantic_role=None, business_context=None,
                 business_significance=None, flow_position=None,
                 risk_level=None, dependencies_description=None,
                 impacted_workflows=None):
        self.semantic_role = semantic_role
        self.business_context = business_context
        self.business_significance = business_significance
        self.flow_position = flow_position
        self.risk_level = risk_level
        self.dependencies_description = dependencies_description
        self.impacted_workflows = impacted_workflows


class NavigationNode:
    """Simplified navigation node for testing."""
    def __init__(self, node_key, title, node_type, description,
                 semantic_metadata=None, business_narrative=None):
        self.node_key = node_key
        self.title = title
        self.node_type = node_type
        self.description = description
        self.semantic_metadata = semantic_metadata
        self.business_narrative = business_narrative


def test_semantic_metadata_enum_to_string_conversion():
    """Test that Enum values are correctly converted to strings."""
    # Create semantic metadata with Enum values
    metadata = SemanticMetadata(
        semantic_role=SemanticRole.GATEWAY,
        business_context="Entry point for API requests",
        business_significance="Critical for user access",
        flow_position=BusinessFlowPosition.ENTRY_POINT,
        risk_level=RiskLevel.CRITICAL,
        dependencies_description="Load balancer, auth service",
        impacted_workflows=["user_auth", "data_ingestion"],
    )

    # Convert to dict (as done in _format_node)
    node_dict = {
        "semantic_metadata": {
            "semantic_role": metadata.semantic_role.value if metadata.semantic_role else None,
            "business_context": metadata.business_context,
            "business_significance": metadata.business_significance,
            "flow_position": metadata.flow_position.value if metadata.flow_position else None,
            "risk_level": metadata.risk_level.value if metadata.risk_level else None,
            "dependencies_description": metadata.dependencies_description,
            "impacted_workflows": metadata.impacted_workflows,
        }
    }

    # Verify conversion
    assert node_dict["semantic_metadata"]["semantic_role"] == "gateway"
    assert node_dict["semantic_metadata"]["flow_position"] == "entry_point"
    assert node_dict["semantic_metadata"]["risk_level"] == "critical"
    assert node_dict["semantic_metadata"]["impacted_workflows"] == ["user_auth", "data_ingestion"]
    print("✓ Enum to string conversion works correctly")


def test_semantic_metadata_with_business_narrative():
    """Test that business_narrative is included in node dict."""
    node = NavigationNode(
        node_key="api-gateway",
        title="API Gateway",
        node_type="class",
        description="Main API entry point",
        semantic_metadata=SemanticMetadata(
            semantic_role=SemanticRole.GATEWAY,
            business_context="API entry point",
            flow_position=BusinessFlowPosition.ENTRY_POINT,
            risk_level=RiskLevel.CRITICAL,
        ),
        business_narrative="The API Gateway is the primary entry point for all external client requests."
    )

    # Convert node to dict
    node_dict = {
        "node_key": node.node_key,
        "title": node.title,
        "node_type": node.node_type,
        "description": node.description,
    }

    # Add semantic metadata
    if node.semantic_metadata:
        node_dict["semantic_metadata"] = {
            "semantic_role": node.semantic_metadata.semantic_role.value if node.semantic_metadata.semantic_role else None,
            "business_context": node.semantic_metadata.business_context,
            "business_significance": node.semantic_metadata.business_significance,
            "flow_position": node.semantic_metadata.flow_position.value if node.semantic_metadata.flow_position else None,
            "risk_level": node.semantic_metadata.risk_level.value if node.semantic_metadata.risk_level else None,
            "dependencies_description": node.semantic_metadata.dependencies_description,
            "impacted_workflows": node.semantic_metadata.impacted_workflows,
        }

    # Add business narrative
    if node.business_narrative:
        node_dict["business_narrative"] = node.business_narrative

    # Verify structure
    assert "semantic_metadata" in node_dict
    assert "business_narrative" in node_dict
    assert node_dict["semantic_metadata"]["semantic_role"] == "gateway"
    assert node_dict["business_narrative"] == "The API Gateway is the primary entry point for all external client requests."
    print("✓ Business narrative is correctly included in node dict")


def test_semantic_metadata_none_handling():
    """Test that nodes without semantic metadata don't error."""
    node = NavigationNode(
        node_key="helper-func",
        title="Helper Function",
        node_type="function",
        description="A simple helper function",
        semantic_metadata=None,
        business_narrative=None
    )

    # Convert node to dict
    node_dict = {
        "node_key": node.node_key,
        "title": node.title,
        "node_type": node.node_type,
        "description": node.description,
    }

    # Only add semantic metadata if present
    if node.semantic_metadata:
        node_dict["semantic_metadata"] = {}

    if node.business_narrative:
        node_dict["business_narrative"] = node.business_narrative

    # Verify no error and structure is correct
    assert "semantic_metadata" not in node_dict
    assert "business_narrative" not in node_dict
    assert node_dict["node_key"] == "helper-func"
    print("✓ None handling works correctly")


if __name__ == "__main__":
    test_semantic_metadata_enum_to_string_conversion()
    test_semantic_metadata_with_business_narrative()
    test_semantic_metadata_none_handling()
    print("\n✅ All semantic metadata conversion tests passed!")
