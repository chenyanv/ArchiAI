import pytest
from pydantic import ValidationError

from component_agent.schemas import (
    DRILLABLE_NODE_TYPES,
    NavigationAction,
    NavigationNode,
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
