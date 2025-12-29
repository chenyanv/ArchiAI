import pytest
from pydantic import ValidationError

from component_agent.schemas import (
    DRILLABLE_NODE_TYPES,
    BusinessFlowPosition,
    NavigationAction,
    NavigationNode,
    RiskLevel,
    SemanticMetadata,
    SemanticRole,
    coerce_subagent_payload,
)


def test_coerce_subagent_payload_infers_objectives():
    card = {
        "objective": [
            "Trace ingestion to chunking.",
            "  ",
            42,
        ]
    }
    payload = coerce_subagent_payload(card)
    assert payload is not None
    assert payload["objective"] == ["Trace ingestion to chunking."]


def test_coerce_subagent_payload_preserves_existing_directives():
    card = {
        "objective": ["fallback"],
        "subagent_payload": {"objective": ["primary"], "notes": ["keep me"]},
    }
    payload = coerce_subagent_payload(card)
    assert payload["objective"] == ["primary"]
    assert payload["notes"] == ["keep me"]


# === Tests for NavigationNode action.kind validation ===


class TestDrillableNodeTypeValidation:
    """Test that drillable node types must use component_drilldown action."""

    @pytest.mark.parametrize("node_type", DRILLABLE_NODE_TYPES)
    def test_drillable_node_with_component_drilldown_succeeds(self, node_type):
        """Drillable node types with component_drilldown action should succeed."""
        node = NavigationNode(
            node_key="test-node",
            title="Test Node",
            node_type=node_type,
            description="Test description",
            action=NavigationAction(kind="component_drilldown", target_id="target-123"),
        )
        assert node.action.kind == "component_drilldown"

    @pytest.mark.parametrize("node_type", DRILLABLE_NODE_TYPES)
    def test_drillable_node_with_inspect_source_fails(self, node_type):
        """Drillable node types with inspect_source action should fail."""
        with pytest.raises(ValidationError) as exc_info:
            NavigationNode(
                node_key="test-node",
                title="Test Node",
                node_type=node_type,
                description="Test description",
                action=NavigationAction(kind="inspect_source"),
            )
        assert "component_drilldown" in str(exc_info.value)

    @pytest.mark.parametrize(
        "invalid_kind", ["inspect_node", "inspect_tool", "graph_overlay"]
    )
    def test_drillable_node_with_invalid_action_fails(self, invalid_kind):
        """Drillable node types with unsupported action kinds should fail."""
        with pytest.raises(ValidationError) as exc_info:
            NavigationNode(
                node_key="test-node",
                title="Test Node",
                node_type="class",
                description="Test description",
                action=NavigationAction(kind=invalid_kind),
            )
        assert "component_drilldown" in str(exc_info.value)


class TestNonDrillableNodeTypeValidation:
    """Test that non-drillable node types must use inspect_source action."""

    NON_DRILLABLE_TYPES = {
        "pipeline",
        "agent",
        "file",
        "function",
        "model",
        "dataset",
        "prompt",
        "tool",
        "graph",
        "source",
    }

    @pytest.mark.parametrize("node_type", NON_DRILLABLE_TYPES)
    def test_non_drillable_node_with_inspect_source_succeeds(self, node_type):
        """Non-drillable node types with inspect_source action should succeed."""
        node = NavigationNode(
            node_key="test-node",
            title="Test Node",
            node_type=node_type,
            description="Test description",
            action=NavigationAction(kind="inspect_source"),
        )
        assert node.action.kind == "inspect_source"

    @pytest.mark.parametrize("node_type", NON_DRILLABLE_TYPES)
    def test_non_drillable_node_with_component_drilldown_fails(self, node_type):
        """Non-drillable node types with component_drilldown action should fail."""
        with pytest.raises(ValidationError) as exc_info:
            NavigationNode(
                node_key="test-node",
                title="Test Node",
                node_type=node_type,
                description="Test description",
                action=NavigationAction(kind="component_drilldown", target_id="target-123"),
            )
        assert "inspect_source" in str(exc_info.value)


class TestDrillableNodeTypesConstant:
    """Test that DRILLABLE_NODE_TYPES constant is properly defined."""

    def test_drillable_node_types_is_set(self):
        """DRILLABLE_NODE_TYPES should be a non-empty set."""
        assert isinstance(DRILLABLE_NODE_TYPES, set)
        assert len(DRILLABLE_NODE_TYPES) > 0

    def test_drillable_node_types_contains_expected_values(self):
        """DRILLABLE_NODE_TYPES should contain all expected node types."""
        expected = {"class", "workflow", "service", "category", "capability"}
        assert DRILLABLE_NODE_TYPES == expected


# === Tests for Semantic Metadata ===


class TestSemanticRoleEnum:
    """Test that SemanticRole enum is properly defined with all expected values."""

    def test_semantic_role_has_all_expected_values(self):
        """SemanticRole should contain all expected role classifications."""
        expected_roles = {
            "gateway",
            "processor",
            "sink",
            "orchestrator",
            "validator",
            "transformer",
            "aggregator",
            "dispatcher",
            "adapter",
            "mediator",
            "repository",
            "factory",
            "strategy",
        }
        actual_roles = {role.value for role in SemanticRole}
        assert actual_roles == expected_roles

    def test_semantic_role_is_string_enum(self):
        """SemanticRole should be usable as a string."""
        assert SemanticRole.GATEWAY.value == "gateway"
        assert isinstance(SemanticRole.PROCESSOR.value, str)


class TestBusinessFlowPositionEnum:
    """Test that BusinessFlowPosition enum is properly defined."""

    def test_business_flow_position_has_all_expected_values(self):
        """BusinessFlowPosition should contain all expected flow positions."""
        expected_positions = {
            "entry_point",
            "validation",
            "processing",
            "transformation",
            "aggregation",
            "storage",
            "output",
            "error_handling",
        }
        actual_positions = {pos.value for pos in BusinessFlowPosition}
        assert actual_positions == expected_positions


class TestRiskLevelEnum:
    """Test that RiskLevel enum is properly defined."""

    def test_risk_level_has_all_expected_values(self):
        """RiskLevel should contain all expected risk levels."""
        expected_levels = {"critical", "high", "medium", "low"}
        actual_levels = {level.value for level in RiskLevel}
        assert actual_levels == expected_levels


class TestSemanticMetadata:
    """Test SemanticMetadata model and its fields."""

    def test_semantic_metadata_with_all_fields_populated(self):
        """SemanticMetadata should accept all fields when properly populated."""
        metadata = SemanticMetadata(
            semantic_role=SemanticRole.GATEWAY,
            business_context="Handles incoming API requests and routes them to appropriate processors.",
            business_significance="Critical entry point for all external data ingestion.",
            flow_position=BusinessFlowPosition.ENTRY_POINT,
            risk_level=RiskLevel.CRITICAL,
            dependencies_description="Depends on load balancer and message queue.",
            impacted_workflows=["data_ingestion", "user_onboarding"],
        )
        assert metadata.semantic_role == SemanticRole.GATEWAY
        assert metadata.business_context is not None
        assert metadata.flow_position == BusinessFlowPosition.ENTRY_POINT
        assert len(metadata.impacted_workflows) == 2

    def test_semantic_metadata_with_minimal_fields(self):
        """SemanticMetadata should work with minimal/no fields (all optional)."""
        metadata = SemanticMetadata()
        assert metadata.semantic_role is None
        assert metadata.business_context is None
        assert metadata.impacted_workflows == []

    def test_semantic_metadata_with_only_role(self):
        """SemanticMetadata should accept just a semantic role."""
        metadata = SemanticMetadata(semantic_role=SemanticRole.PROCESSOR)
        assert metadata.semantic_role == SemanticRole.PROCESSOR
        assert metadata.business_context is None
        assert metadata.impacted_workflows == []

    def test_semantic_metadata_impacted_workflows_default_is_list(self):
        """impacted_workflows should default to empty list."""
        metadata = SemanticMetadata(semantic_role=SemanticRole.SINK)
        assert isinstance(metadata.impacted_workflows, list)
        assert metadata.impacted_workflows == []

    def test_semantic_metadata_can_add_workflows(self):
        """Should be able to add multiple impacted workflows."""
        workflows = ["payment_processing", "settlement", "reporting"]
        metadata = SemanticMetadata(
            semantic_role=SemanticRole.SINK,
            impacted_workflows=workflows,
        )
        assert metadata.impacted_workflows == workflows


class TestNavigationNodeWithSemanticMetadata:
    """Test NavigationNode integration with semantic metadata."""

    def test_navigation_node_with_semantic_metadata(self):
        """NavigationNode should accept semantic_metadata and business_narrative."""
        semantic_meta = SemanticMetadata(
            semantic_role=SemanticRole.ORCHESTRATOR,
            business_context="Orchestrates workflow execution across multiple processors.",
            risk_level=RiskLevel.HIGH,
        )
        node = NavigationNode(
            node_key="workflow-orchestrator",
            title="Workflow Orchestrator",
            node_type="class",
            description="Manages workflow state and routing.",
            action=NavigationAction(kind="component_drilldown", target_id="orch-123"),
            semantic_metadata=semantic_meta,
            business_narrative="The Workflow Orchestrator is the central coordinator that ensures all workflow steps execute in proper sequence.",
        )
        assert node.semantic_metadata is not None
        assert node.semantic_metadata.semantic_role == SemanticRole.ORCHESTRATOR
        assert node.business_narrative is not None

    def test_navigation_node_without_semantic_metadata(self):
        """NavigationNode should work without semantic metadata (backward compatible)."""
        node = NavigationNode(
            node_key="legacy-node",
            title="Legacy Node",
            node_type="function",
            description="Old node without semantic info.",
            action=NavigationAction(kind="inspect_source"),
        )
        assert node.semantic_metadata is None
        assert node.business_narrative is None

    def test_navigation_node_with_only_semantic_metadata(self):
        """NavigationNode should accept just semantic metadata without narrative."""
        metadata = SemanticMetadata(semantic_role=SemanticRole.VALIDATOR)
        node = NavigationNode(
            node_key="validator",
            title="Data Validator",
            node_type="class",
            description="Validates input data.",
            action=NavigationAction(kind="component_drilldown", target_id="val-456"),
            semantic_metadata=metadata,
        )
        assert node.semantic_metadata is not None
        assert node.business_narrative is None

    def test_navigation_node_with_complete_semantic_context(self):
        """NavigationNode should handle full semantic context with drillable type."""
        metadata = SemanticMetadata(
            semantic_role=SemanticRole.TRANSFORMER,
            business_context="Transforms raw data into standardized format.",
            business_significance="Ensures data consistency across the system.",
            flow_position=BusinessFlowPosition.TRANSFORMATION,
            risk_level=RiskLevel.MEDIUM,
            dependencies_description="Depends on format definitions and validation rules.",
            impacted_workflows=["data_pipeline", "analytics"],
        )
        node = NavigationNode(
            node_key="data-transformer",
            title="Data Transformer",
            node_type="class",
            description="Implements data transformation logic.",
            action=NavigationAction(kind="component_drilldown", target_id="trans-789"),
            semantic_metadata=metadata,
            business_narrative="The Data Transformer ensures all incoming data is converted to standard internal format before processing.",
            score=0.95,
        )
        assert node.semantic_metadata.semantic_role == SemanticRole.TRANSFORMER
        assert node.semantic_metadata.flow_position == BusinessFlowPosition.TRANSFORMATION
        assert len(node.semantic_metadata.impacted_workflows) == 2
        assert node.business_narrative is not None
        assert node.action.kind == "component_drilldown"
