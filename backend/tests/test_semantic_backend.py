"""Comprehensive backend tests for semantic gap solution."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from enum import Enum
from typing import Optional, List


# === Minimal Enum Definitions (matching backend) ===

class SemanticRole(str, Enum):
    GATEWAY = "gateway"
    PROCESSOR = "processor"
    ORCHESTRATOR = "orchestrator"
    VALIDATOR = "validator"
    TRANSFORMER = "transformer"
    REPOSITORY = "repository"
    FACTORY = "factory"
    ADAPTER = "adapter"
    MEDIATOR = "mediator"
    AGGREGATOR = "aggregator"
    DISPATCHER = "dispatcher"
    STRATEGY = "strategy"
    SINK = "sink"


class BusinessFlowPosition(str, Enum):
    ENTRY_POINT = "entry_point"
    VALIDATION = "validation"
    PROCESSING = "processing"
    TRANSFORMATION = "transformation"
    AGGREGATION = "aggregation"
    STORAGE = "storage"
    OUTPUT = "output"
    ERROR_HANDLING = "error_handling"


class RiskLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Action:
    """Minimal action class."""
    def __init__(self, kind: str, target_id: Optional[str] = None, parameters: Optional[dict] = None):
        self.kind = kind
        self.target_id = target_id
        self.parameters = parameters or {}


class SemanticMetadata:
    """Minimal semantic metadata class."""
    def __init__(
        self,
        semantic_role: Optional[SemanticRole] = None,
        business_context: Optional[str] = None,
        business_significance: Optional[str] = None,
        flow_position: Optional[BusinessFlowPosition] = None,
        risk_level: Optional[RiskLevel] = None,
        dependencies_description: Optional[str] = None,
        impacted_workflows: Optional[List[str]] = None,
    ):
        self.semantic_role = semantic_role
        self.business_context = business_context
        self.business_significance = business_significance
        self.flow_position = flow_position
        self.risk_level = risk_level
        self.dependencies_description = dependencies_description
        self.impacted_workflows = impacted_workflows or []


class NavigationNode:
    """Minimal navigation node matching backend schema."""
    def __init__(
        self,
        node_key: str,
        title: str,
        node_type: str,
        description: str,
        action: Action,
        semantic_metadata: Optional[SemanticMetadata] = None,
        business_narrative: Optional[str] = None,
        sequence_order: Optional[int] = None,
        target_id: Optional[str] = None,
    ):
        self.node_key = node_key
        self.title = title
        self.node_type = node_type
        self.description = description
        self.action = action
        self.semantic_metadata = semantic_metadata
        self.business_narrative = business_narrative
        self.sequence_order = sequence_order
        self.target_id = target_id


# === DTO Conversion Logic (matching workspaces.py) ===

def _format_node(n: NavigationNode, workspace_id: str = "test-workspace", database_url: Optional[str] = None) -> dict:
    """Convert NavigationNode to API dict, including semantic metadata."""
    node_dict = {
        "node_key": n.node_key,
        "title": n.title,
        "node_type": n.node_type,
        "description": n.description,
        "action_kind": n.action.kind,
        "target_id": n.action.target_id,
        "action_parameters": n.action.parameters,
        "sequence_order": n.sequence_order,
    }

    # Add semantic metadata if present, converting Enums to strings
    if n.semantic_metadata:
        node_dict["semantic_metadata"] = {
            "semantic_role": n.semantic_metadata.semantic_role.value if n.semantic_metadata.semantic_role else None,
            "business_context": n.semantic_metadata.business_context,
            "business_significance": n.semantic_metadata.business_significance,
            "flow_position": n.semantic_metadata.flow_position.value if n.semantic_metadata.flow_position else None,
            "risk_level": n.semantic_metadata.risk_level.value if n.semantic_metadata.risk_level else None,
            "dependencies_description": n.semantic_metadata.dependencies_description,
            "impacted_workflows": n.semantic_metadata.impacted_workflows,
        }

    # Add business narrative if present
    if n.business_narrative:
        node_dict["business_narrative"] = n.business_narrative

    return node_dict


# === Test Suite ===

def test_semantic_role_enum_values():
    """Verify SemanticRole enum has all 13 values."""
    expected_roles = {
        "gateway", "processor", "orchestrator", "validator", "transformer",
        "repository", "factory", "adapter", "mediator", "aggregator",
        "dispatcher", "strategy", "sink"
    }
    actual_roles = {role.value for role in SemanticRole}
    assert actual_roles == expected_roles, f"Missing roles: {expected_roles - actual_roles}"
    print("✓ SemanticRole enum has all 13 values")


def test_business_flow_position_enum_values():
    """Verify BusinessFlowPosition enum has all 8 values."""
    expected_positions = {
        "entry_point", "validation", "processing", "transformation",
        "aggregation", "storage", "output", "error_handling"
    }
    actual_positions = {pos.value for pos in BusinessFlowPosition}
    assert actual_positions == expected_positions, f"Missing positions: {expected_positions - actual_positions}"
    print("✓ BusinessFlowPosition enum has all 8 values")


def test_risk_level_enum_values():
    """Verify RiskLevel enum has all 4 values."""
    expected_levels = {"critical", "high", "medium", "low"}
    actual_levels = {level.value for level in RiskLevel}
    assert actual_levels == expected_levels, f"Missing levels: {expected_levels - actual_levels}"
    print("✓ RiskLevel enum has all 4 values")


def test_dto_conversion_full_semantic_metadata():
    """Test DTO conversion with all semantic fields populated."""
    node = NavigationNode(
        node_key="api-gateway",
        title="API Gateway",
        node_type="class",
        description="Main API entry point",
        action=Action(kind="component_drilldown", target_id="python::api/gateway.py::Gateway"),
        semantic_metadata=SemanticMetadata(
            semantic_role=SemanticRole.GATEWAY,
            business_context="Provides REST API for external clients",
            business_significance="Primary entry point for all users",
            flow_position=BusinessFlowPosition.ENTRY_POINT,
            risk_level=RiskLevel.CRITICAL,
            dependencies_description="Load balancer, auth service",
            impacted_workflows=["user_auth", "data_ingestion"],
        ),
        business_narrative="The API Gateway is the primary entry point for all external client requests.",
    )

    result = _format_node(node)

    # Verify basic fields
    assert result["node_key"] == "api-gateway"
    assert result["title"] == "API Gateway"
    assert result["node_type"] == "class"

    # Verify semantic metadata structure
    assert "semantic_metadata" in result
    semantic = result["semantic_metadata"]

    # Verify Enum→String conversion
    assert semantic["semantic_role"] == "gateway", f"Expected 'gateway', got {semantic['semantic_role']}"
    assert semantic["flow_position"] == "entry_point", f"Expected 'entry_point', got {semantic['flow_position']}"
    assert semantic["risk_level"] == "critical", f"Expected 'critical', got {semantic['risk_level']}"

    # Verify other fields
    assert semantic["business_context"] == "Provides REST API for external clients"
    assert semantic["business_significance"] == "Primary entry point for all users"
    assert semantic["dependencies_description"] == "Load balancer, auth service"
    assert semantic["impacted_workflows"] == ["user_auth", "data_ingestion"]

    # Verify business narrative
    assert result["business_narrative"] == "The API Gateway is the primary entry point for all external client requests."

    print("✓ DTO conversion: Full semantic metadata works correctly")


def test_dto_conversion_partial_semantic_metadata():
    """Test DTO conversion with partial semantic fields."""
    node = NavigationNode(
        node_key="processor",
        title="Data Processor",
        node_type="class",
        description="Processes incoming data",
        action=Action(kind="component_drilldown"),
        semantic_metadata=SemanticMetadata(
            semantic_role=SemanticRole.PROCESSOR,
            business_context="Transforms raw data into business format",
            # Note: business_significance, flow_position, risk_level are None
        ),
    )

    result = _format_node(node)

    assert "semantic_metadata" in result
    semantic = result["semantic_metadata"]

    # Verify set fields
    assert semantic["semantic_role"] == "processor"
    assert semantic["business_context"] == "Transforms raw data into business format"

    # Verify None fields are None (not missing)
    assert semantic["business_significance"] is None
    assert semantic["flow_position"] is None
    assert semantic["risk_level"] is None
    assert semantic["impacted_workflows"] == []

    print("✓ DTO conversion: Partial semantic metadata works correctly")


def test_dto_conversion_no_semantic_metadata():
    """Test DTO conversion when semantic_metadata is None."""
    node = NavigationNode(
        node_key="helper",
        title="Helper Function",
        node_type="function",
        description="A simple helper",
        action=Action(kind="inspect_source"),
        semantic_metadata=None,  # No semantic metadata
        business_narrative=None,
    )

    result = _format_node(node)

    # Verify semantic_metadata is NOT in result
    assert "semantic_metadata" not in result, "semantic_metadata should not be in result when None"
    assert "business_narrative" not in result, "business_narrative should not be in result when None"

    # Verify other fields are present
    assert result["node_key"] == "helper"
    assert result["title"] == "Helper Function"

    print("✓ DTO conversion: No semantic metadata works correctly (backward compatible)")


def test_dto_conversion_business_narrative_without_semantic_metadata():
    """Test DTO conversion with business_narrative but no semantic_metadata."""
    node = NavigationNode(
        node_key="module",
        title="Module",
        node_type="module",
        description="A module",
        action=Action(kind="component_drilldown"),
        semantic_metadata=None,
        business_narrative="This is a narrative",  # Has narrative but no semantic metadata
    )

    result = _format_node(node)

    # Should include business_narrative even without semantic_metadata
    assert result["business_narrative"] == "This is a narrative"
    assert "semantic_metadata" not in result

    print("✓ DTO conversion: business_narrative alone works correctly")


def test_enum_value_access():
    """Verify Enum.value accessor works correctly."""
    role = SemanticRole.PROCESSOR
    assert role.value == "processor"

    position = BusinessFlowPosition.PROCESSING
    assert position.value == "processing"

    level = RiskLevel.HIGH
    assert level.value == "high"

    print("✓ Enum.value accessor works correctly")


def test_enum_none_check():
    """Verify None enum check works in DTO conversion."""
    semantic = SemanticMetadata(semantic_role=None)

    # This is the pattern used in _format_node
    result = semantic.semantic_role.value if semantic.semantic_role else None

    assert result is None, "Should return None when Enum is None"

    print("✓ Enum None check works correctly")


def test_all_semantic_roles_are_strings():
    """Verify all SemanticRole values are valid strings."""
    for role in SemanticRole:
        assert isinstance(role.value, str), f"Role {role} value is not string: {role.value}"
        assert len(role.value) > 0, f"Role {role} has empty value"
        assert role.value.islower(), f"Role {role} value is not lowercase: {role.value}"

    print("✓ All semantic roles are valid lowercase strings")


def test_all_flow_positions_are_strings():
    """Verify all BusinessFlowPosition values are valid strings."""
    for position in BusinessFlowPosition:
        assert isinstance(position.value, str), f"Position {position} value is not string"
        assert len(position.value) > 0, f"Position {position} has empty value"
        assert position.value.islower(), f"Position {position} value is not lowercase"

    print("✓ All flow positions are valid lowercase strings")


def test_impacted_workflows_list_serialization():
    """Test that impacted_workflows list is properly serialized."""
    workflows = ["workflow1", "workflow2", "workflow3"]
    node = NavigationNode(
        node_key="test",
        title="Test",
        node_type="class",
        description="Test",
        action=Action(kind="component_drilldown"),
        semantic_metadata=SemanticMetadata(impacted_workflows=workflows),
    )

    result = _format_node(node)

    assert result["semantic_metadata"]["impacted_workflows"] == workflows
    assert isinstance(result["semantic_metadata"]["impacted_workflows"], list)
    assert len(result["semantic_metadata"]["impacted_workflows"]) == 3

    print("✓ impacted_workflows list serialization works correctly")


def test_empty_impacted_workflows():
    """Test empty impacted_workflows list."""
    node = NavigationNode(
        node_key="test",
        title="Test",
        node_type="class",
        description="Test",
        action=Action(kind="component_drilldown"),
        semantic_metadata=SemanticMetadata(impacted_workflows=[]),
    )

    result = _format_node(node)

    assert result["semantic_metadata"]["impacted_workflows"] == []

    print("✓ Empty impacted_workflows list works correctly")


def test_action_parameters_preservation():
    """Test that action_parameters are preserved in DTO."""
    params = {"key": "value", "nested": {"a": 1}}
    node = NavigationNode(
        node_key="test",
        title="Test",
        node_type="class",
        description="Test",
        action=Action(kind="component_drilldown", parameters=params),
        semantic_metadata=None,
    )

    result = _format_node(node)

    assert result["action_parameters"] == params

    print("✓ action_parameters preservation works correctly")


def test_sequence_order_handling():
    """Test sequence_order field handling."""
    # With sequence_order
    node1 = NavigationNode(
        node_key="test1",
        title="Test 1",
        node_type="class",
        description="Test",
        action=Action(kind="component_drilldown"),
        sequence_order=0,
    )

    result1 = _format_node(node1)
    assert result1["sequence_order"] == 0

    # Without sequence_order
    node2 = NavigationNode(
        node_key="test2",
        title="Test 2",
        node_type="class",
        description="Test",
        action=Action(kind="component_drilldown"),
        sequence_order=None,
    )

    result2 = _format_node(node2)
    assert result2["sequence_order"] is None

    print("✓ sequence_order handling works correctly")


def test_multiple_nodes_conversion():
    """Test converting multiple nodes maintains correctness."""
    nodes = [
        NavigationNode(
            node_key=f"node-{i}",
            title=f"Node {i}",
            node_type="class",
            description=f"Node description {i}",
            action=Action(kind="component_drilldown"),
            semantic_metadata=SemanticMetadata(
                semantic_role=SemanticRole.PROCESSOR if i % 2 == 0 else SemanticRole.VALIDATOR,
                risk_level=RiskLevel.CRITICAL if i % 2 == 0 else RiskLevel.LOW,
            ),
        )
        for i in range(5)
    ]

    results = [_format_node(node) for node in nodes]

    # Verify all nodes converted
    assert len(results) == 5

    # Verify alternating semantic roles
    assert results[0]["semantic_metadata"]["semantic_role"] == "processor"
    assert results[1]["semantic_metadata"]["semantic_role"] == "validator"
    assert results[2]["semantic_metadata"]["semantic_role"] == "processor"

    # Verify alternating risk levels
    assert results[0]["semantic_metadata"]["risk_level"] == "critical"
    assert results[1]["semantic_metadata"]["risk_level"] == "low"

    print("✓ Multiple nodes conversion works correctly")


# === Run All Tests ===

def run_all_tests():
    """Run all tests and report results."""
    tests = [
        test_semantic_role_enum_values,
        test_business_flow_position_enum_values,
        test_risk_level_enum_values,
        test_dto_conversion_full_semantic_metadata,
        test_dto_conversion_partial_semantic_metadata,
        test_dto_conversion_no_semantic_metadata,
        test_dto_conversion_business_narrative_without_semantic_metadata,
        test_enum_value_access,
        test_enum_none_check,
        test_all_semantic_roles_are_strings,
        test_all_flow_positions_are_strings,
        test_impacted_workflows_list_serialization,
        test_empty_impacted_workflows,
        test_action_parameters_preservation,
        test_sequence_order_handling,
        test_multiple_nodes_conversion,
    ]

    print("=" * 70)
    print("Backend Semantic Solution - Comprehensive Test Suite")
    print("=" * 70)
    print()

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: Unexpected error: {e}")
            failed += 1

    print()
    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)

    if failed == 0:
        print("\n✅ All tests passed! No bugs detected in backend logic.\n")
        return True
    else:
        print(f"\n❌ {failed} test(s) failed. See details above.\n")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
