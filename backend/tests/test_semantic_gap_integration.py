"""Integration tests for semantic gap solution: code structure to business meaning bridge.

This test suite verifies that semantic metadata flows correctly through:
1. Backend schema validation (SemanticMetadata)
2. LLM prompt generation (semantic_analyzer)
3. API DTO serialization (NavigationNodeDTO with semantic fields)
4. Frontend type definitions (NavigationNode with semantic_metadata)
"""

import pytest
from component_agent.schemas import (
    NavigationNode,
    NavigationAction,
    SemanticMetadata,
    SemanticRole,
    BusinessFlowPosition,
    RiskLevel,
)
from component_agent.semantic_analyzer import (
    build_semantic_extraction_prompt,
    format_structural_findings,
    parse_semantic_response,
)
from api.schemas import NavigationNodeDTO, SemanticMetadataDTO


class TestSemanticMetadataEnd2End:
    """Test semantic metadata through entire system."""

    def test_semantic_metadata_schema_validation_full_fields(self):
        """SemanticMetadata should validate all semantic fields."""
        metadata = SemanticMetadata(
            semantic_role=SemanticRole.GATEWAY,
            business_context="Entry point for external API requests",
            business_significance="Critical for user access",
            flow_position=BusinessFlowPosition.ENTRY_POINT,
            risk_level=RiskLevel.CRITICAL,
            dependencies_description="Load balancer, authentication service",
            impacted_workflows=["user_auth", "data_ingestion"],
        )

        assert metadata.semantic_role == SemanticRole.GATEWAY
        assert metadata.flow_position == BusinessFlowPosition.ENTRY_POINT
        assert metadata.risk_level == RiskLevel.CRITICAL
        assert len(metadata.impacted_workflows) == 2

    def test_navigation_node_with_semantic_metadata_required(self):
        """NavigationNode must accept semantic_metadata as optional field."""
        semantic_meta = SemanticMetadata(
            semantic_role=SemanticRole.PROCESSOR,
            business_context="Processes uploaded documents",
            risk_level=RiskLevel.HIGH,
            impacted_workflows=["document_processing"],
        )

        node = NavigationNode(
            node_key="doc-processor",
            title="Document Processor",
            node_type="class",
            description="Handles document input processing",
            action=NavigationAction(kind="component_drilldown", target_id="proc-123"),
            semantic_metadata=semantic_meta,
            business_narrative="The Document Processor validates and parses incoming documents before analysis.",
        )

        assert node.semantic_metadata is not None
        assert node.semantic_metadata.semantic_role == SemanticRole.PROCESSOR
        assert node.business_narrative is not None
        assert "Parser" not in node.business_narrative  # Not technical jargon
        assert "validates" in node.business_narrative.lower()  # Business action

    def test_semantic_analyzer_prompt_generation_pattern_a(self):
        """Semantic analyzer should generate Pattern A (Registry) prompts."""
        findings = {
            "class_names": ["BaseParser", "PDFParser", "WordParser"],
            "public_methods": ["parse", "validate"],
            "dependencies": ["file_handler", "validator"],
            "inheritance": "BaseParser -> {PDFParser, WordParser}",
        }

        prompt = build_semantic_extraction_prompt(
            pattern="A",
            component_name="ParserRegistry",
            structural_findings=findings,
        )

        assert "semantic_role" in prompt
        assert "factory" in prompt.lower() or "registry" in prompt.lower()
        assert "business_context" in prompt
        assert "risk_level" in prompt
        assert "impacted_workflows" in prompt

    def test_semantic_analyzer_prompt_generation_pattern_b(self):
        """Semantic analyzer should generate Pattern B (Workflow) prompts."""
        findings = {
            "class_names": ["Orchestrator", "Validator", "Processor"],
            "public_methods": ["execute", "validate", "process"],
            "dependencies": [],
            "inheritance": "None",
        }

        prompt = build_semantic_extraction_prompt(
            pattern="B",
            component_name="WorkflowEngine",
            structural_findings=findings,
        )

        assert "orchestrator" in prompt.lower() or "orchestration" in prompt.lower()
        assert "business_context" in prompt
        assert "flow_position" in prompt

    def test_semantic_analyzer_prompt_generation_pattern_c(self):
        """Semantic analyzer should generate Pattern C (API/Service) prompts."""
        findings = {
            "class_names": ["APIGateway", "AuthHandler", "DataService"],
            "public_methods": ["POST", "GET", "DELETE"],
            "dependencies": ["database", "auth_service"],
            "inheritance": "APIGateway -> {AuthHandler, DataService}",
        }

        prompt = build_semantic_extraction_prompt(
            pattern="C",
            component_name="RestAPI",
            structural_findings=findings,
        )

        assert "gateway" in prompt.lower() or "api" in prompt.lower()
        assert "business_context" in prompt
        assert "risk_level" in prompt

    def test_format_structural_findings(self):
        """format_structural_findings should produce readable findings."""
        findings = {
            "class_names": ["Parser", "Validator"],
            "public_methods": ["parse", "validate"],
            "private_methods": ["_sanitize"],
            "dependencies": ["file_io", "database"],
            "attributes": ["config", "logger"],
        }

        formatted = format_structural_findings(findings, pattern="A")

        assert "Parser" in formatted
        assert "parse" in formatted
        assert "file_io" in formatted
        assert "Validator" in formatted

    def test_semantic_response_parsing(self):
        """parse_semantic_response should convert LLM response to SemanticMetadata."""
        response = {
            "semantic_role": "gateway",
            "business_context": "Entry point for document uploads",
            "business_significance": "Critical for user access",
            "flow_position": "entry_point",
            "risk_level": "critical",
            "dependencies_description": "Load balancer",
            "impacted_workflows": ["document_upload", "analysis"],
        }

        metadata = parse_semantic_response(response)

        assert metadata is not None
        assert metadata.semantic_role == SemanticRole.GATEWAY
        assert metadata.flow_position == BusinessFlowPosition.ENTRY_POINT
        assert metadata.risk_level == RiskLevel.CRITICAL
        assert len(metadata.impacted_workflows) == 2

    def test_api_dto_with_semantic_metadata(self):
        """NavigationNodeDTO should serialize semantic metadata."""
        semantic_dto = SemanticMetadataDTO(
            semantic_role="processor",
            business_context="Processes documents",
            business_significance="Enables document analysis",
            flow_position="processing",
            risk_level="high",
            impacted_workflows=["analysis"],
        )

        node_dto = NavigationNodeDTO(
            node_key="doc-proc",
            title="Document Processor",
            node_type="class",
            description="Processes documents",
            action_kind="component_drilldown",
            target_id="proc-123",
            semantic_metadata=semantic_dto,
            business_narrative="Processes documents for analysis.",
        )

        # Should serialize to JSON
        node_dict = node_dto.model_dump(exclude_none=True)
        assert "semantic_metadata" in node_dict
        assert node_dict["semantic_metadata"]["semantic_role"] == "processor"
        assert "business_narrative" in node_dict

    def test_backward_compatibility_without_semantic_metadata(self):
        """Nodes without semantic metadata should still work (backward compatible)."""
        node = NavigationNode(
            node_key="legacy",
            title="Legacy Node",
            node_type="function",
            description="Old node",
            action=NavigationAction(kind="inspect_source"),
        )

        assert node.semantic_metadata is None
        assert node.business_narrative is None

        node_dto = NavigationNodeDTO(
            node_key="legacy",
            title="Legacy Node",
            node_type="function",
            description="Old node",
            action_kind="inspect_source",
        )

        assert node_dto.semantic_metadata is None
        assert node_dto.business_narrative is None

    def test_semantic_roles_enum_coverage(self):
        """All semantic roles should be defined and accessible."""
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

    def test_flow_positions_enum_coverage(self):
        """All flow positions should be defined."""
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

    def test_risk_levels_enum_coverage(self):
        """All risk levels should be defined."""
        expected_levels = {"critical", "high", "medium", "low"}
        actual_levels = {level.value for level in RiskLevel}
        assert actual_levels == expected_levels

    def test_semantic_metadata_complete_workflow(self):
        """Test complete workflow: create metadata -> serialize -> validate."""
        # 1. Create semantic metadata
        metadata = SemanticMetadata(
            semantic_role=SemanticRole.ORCHESTRATOR,
            business_context="Coordinates workflow execution",
            business_significance="Central coordination point",
            flow_position=BusinessFlowPosition.PROCESSING,
            risk_level=RiskLevel.HIGH,
            dependencies_description="Message queue, state store",
            impacted_workflows=["order_processing", "payment"],
        )

        # 2. Create navigation node with metadata
        node = NavigationNode(
            node_key="workflow-orchestrator",
            title="Workflow Orchestrator",
            node_type="class",
            description="Coordinates workflow execution",
            action=NavigationAction(kind="component_drilldown", target_id="orch-456"),
            semantic_metadata=metadata,
            business_narrative="The Workflow Orchestrator is the central coordinator that ensures all workflow steps execute in proper sequence and state is maintained.",
        )

        # 3. Serialize to DTO
        node_dto = NavigationNodeDTO(
            node_key=node.node_key,
            title=node.title,
            node_type=node.node_type,
            description=node.description,
            action_kind=node.action.kind,
            target_id=node.action.target_id,
            semantic_metadata=SemanticMetadataDTO(
                semantic_role=metadata.semantic_role.value,
                business_context=metadata.business_context,
                business_significance=metadata.business_significance,
                flow_position=metadata.flow_position.value,
                risk_level=metadata.risk_level.value,
                dependencies_description=metadata.dependencies_description,
                impacted_workflows=metadata.impacted_workflows,
            ),
            business_narrative=node.business_narrative,
        )

        # 4. Verify serialization
        dto_dict = node_dto.model_dump()
        assert dto_dict["semantic_metadata"]["semantic_role"] == "orchestrator"
        assert len(dto_dict["semantic_metadata"]["impacted_workflows"]) == 2
        assert "Orchestrator" in dto_dict["business_narrative"]

        # 5. JSON should be serializable (for API response)
        import json
        json_str = json.dumps(dto_dict)
        restored = json.loads(json_str)
        assert restored["semantic_metadata"]["semantic_role"] == "orchestrator"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
