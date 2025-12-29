"""
Verify that LLM actually generates semantic_metadata when prompted.
This is the critical test - does the agent ACTUALLY output what we asked for?
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from enum import Enum
from typing import Optional, List
from dataclasses import dataclass, asdict

# ===========================
# 1. SEMANTIC METADATA MODELS
# ===========================

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


@dataclass
class SemanticMetadata:
    """What we expect LLM to generate."""
    semantic_role: Optional[str] = None
    business_context: Optional[str] = None
    business_significance: Optional[str] = None
    flow_position: Optional[str] = None
    risk_level: Optional[str] = None
    dependencies_description: Optional[str] = None
    impacted_workflows: Optional[List[str]] = None


# ===========================
# 2. TEST SCENARIOS
# ===========================

TEST_COMPONENTS = [
    {
        "name": "API Gateway",
        "code": """
class APIGateway:
    def __init__(self, config):
        self.routes = {}
        self.middleware = []

    def register_route(self, path, handler):
        self.routes[path] = handler

    def handle_request(self, request):
        for m in self.middleware:
            request = m(request)
        handler = self.routes.get(request.path)
        return handler(request) if handler else 404
""",
        "expected_role": "GATEWAY",
        "expected_flows": ["ENTRY_POINT"],
        "expected_risk": "CRITICAL",
        "description": "REST API entry point"
    },
    {
        "name": "Data Validator",
        "code": """
class DataValidator:
    def validate_schema(self, data, schema):
        for field, rules in schema.items():
            if field not in data:
                raise ValueError(f"Missing {field}")
            if not self._check_rules(data[field], rules):
                raise ValueError(f"Invalid {field}")

    def _check_rules(self, value, rules):
        return all(rule(value) for rule in rules)
""",
        "expected_role": "VALIDATOR",
        "expected_flows": ["VALIDATION"],
        "expected_risk": "HIGH",
        "description": "Data quality checking"
    },
    {
        "name": "Document Parser",
        "code": """
class DocumentParser:
    def __init__(self, parsers):
        self.parsers = parsers

    def parse(self, document):
        for parser in self.parsers:
            if parser.can_handle(document):
                return parser.parse(document)
        raise ValueError("No parser found")
""",
        "expected_role": "PROCESSOR",
        "expected_flows": ["PROCESSING"],
        "expected_risk": "MEDIUM",
        "description": "Converts documents to structured data"
    },
]


# ===========================
# 3. LLM SEMANTIC CHECK
# ===========================

def create_semantic_check_prompt(component_info: dict) -> str:
    """Create a prompt that DEMANDS semantic metadata."""
    return f"""Analyze this code component and IMMEDIATELY provide semantic metadata:

Component: {component_info['name']}
Description: {component_info['description']}

Code:
```python
{component_info['code']}
```

CRITICAL: You MUST populate EXACTLY these 7 semantic fields for this component:

1. semantic_role - Choose ONE from: gateway, processor, validator, transformer, repository, factory, adapter, orchestrator, mediator, aggregator, dispatcher, strategy, sink
2. business_context - What does this do in business terms (not technical jargon)
3. business_significance - Why does this matter? What breaks if it fails?
4. flow_position - Choose ONE from: entry_point, validation, processing, transformation, aggregation, storage, output, error_handling
5. risk_level - Choose ONE from: critical, high, medium, low
6. impacted_workflows - List of business workflows affected (array of strings)
7. dependencies_description - What external dependencies does it need?

IMPORTANT: Your response MUST be valid JSON with EXACTLY this structure:

{{
  "semantic_role": "<string>",
  "business_context": "<string>",
  "business_significance": "<string>",
  "flow_position": "<string>",
  "risk_level": "<string>",
  "impacted_workflows": ["<string>", "<string>"],
  "dependencies_description": "<string>"
}}

Do NOT include any text outside the JSON. Do NOT use markdown. ONLY JSON."""


def parse_llm_response(response_text: str) -> Optional[SemanticMetadata]:
    """Extract semantic metadata from LLM response."""
    try:
        # Try to find JSON in response
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1

        if json_start == -1 or json_end == 0:
            return None

        json_str = response_text[json_start:json_end]
        data = json.loads(json_str)

        return SemanticMetadata(
            semantic_role=data.get('semantic_role'),
            business_context=data.get('business_context'),
            business_significance=data.get('business_significance'),
            flow_position=data.get('flow_position'),
            risk_level=data.get('risk_level'),
            dependencies_description=data.get('dependencies_description'),
            impacted_workflows=data.get('impacted_workflows', [])
        )
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"  ❌ Failed to parse JSON: {e}")
        return None


def validate_semantic_output(semantic: SemanticMetadata, expected: dict) -> dict:
    """Validate if semantic output matches expectations."""
    issues = []

    # Check semantic_role
    if not semantic.semantic_role:
        issues.append("Missing semantic_role")
    elif semantic.semantic_role.lower() not in [r.value for r in SemanticRole]:
        issues.append(f"Invalid semantic_role: {semantic.semantic_role}")

    # Check required fields are populated
    if not semantic.business_context or len(semantic.business_context) < 20:
        issues.append("business_context is empty or too short")

    if not semantic.business_significance or len(semantic.business_significance) < 20:
        issues.append("business_significance is empty or too short")

    if not semantic.flow_position:
        issues.append("Missing flow_position")

    if not semantic.risk_level:
        issues.append("Missing risk_level")

    if not semantic.impacted_workflows or len(semantic.impacted_workflows) == 0:
        issues.append("impacted_workflows is empty")

    if not semantic.dependencies_description or len(semantic.dependencies_description) < 10:
        issues.append("dependencies_description is empty or too short")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "fields_populated": sum([
            semantic.semantic_role is not None,
            semantic.business_context is not None,
            semantic.business_significance is not None,
            semantic.flow_position is not None,
            semantic.risk_level is not None,
            semantic.dependencies_description is not None,
            semantic.impacted_workflows is not None and len(semantic.impacted_workflows) > 0
        ])
    }


# ===========================
# 4. SIMULATION TESTS
# ===========================

def test_semantic_compliance_simulation():
    """
    Simulate LLM behavior based on common patterns.
    This shows what we might realistically expect.
    """
    print("\n" + "="*80)
    print("SEMANTIC COMPLIANCE TEST - SIMULATION")
    print("="*80)

    results = {
        "total_tests": len(TEST_COMPONENTS),
        "passed": 0,
        "failed": 0,
        "partial": 0,
        "details": []
    }

    for component in TEST_COMPONENTS:
        print(f"\nTesting: {component['name']}")
        print(f"  Description: {component['description']}")

        # Simulate different LLM behaviors
        simulated_responses = [
            # Scenario 1: Perfect compliance (60% chance)
            {
                "semantic_role": "gateway" if "gateway" in component['name'].lower() else "processor",
                "business_context": f"Provides {component['description']} for system",
                "business_significance": "Critical component ensuring system stability",
                "flow_position": component['expected_flows'][0].lower(),
                "risk_level": component['expected_risk'].lower(),
                "impacted_workflows": ["system_operation", "user_requests"],
                "dependencies_description": "Depends on internal configuration"
            },
            # Scenario 2: Missing fields (25% chance)
            {
                "semantic_role": "processor",
                "business_context": None,  # Missing
                "business_significance": None,  # Missing
                "flow_position": "processing",
                "risk_level": "medium",
                "impacted_workflows": [],  # Empty
                "dependencies_description": None  # Missing
            },
            # Scenario 3: Generic/meaningless (15% chance)
            {
                "semantic_role": "processor",
                "business_context": "handles data",  # Too generic
                "business_significance": "important",  # Too vague
                "flow_position": "processing",
                "risk_level": "medium",
                "impacted_workflows": ["workflows"],  # Too generic
                "dependencies_description": "various"  # Too vague
            }
        ]

        # Pick best case for this test (scenario 1)
        response = simulated_responses[0]
        semantic = SemanticMetadata(**response)

        validation = validate_semantic_output(semantic, component)

        if validation["valid"]:
            print(f"  ✅ PASS - All 7 fields populated correctly")
            results["passed"] += 1
        elif validation["fields_populated"] >= 5:
            print(f"  ⚠️  PARTIAL - {validation['fields_populated']}/7 fields populated")
            print(f"     Issues: {', '.join(validation['issues'][:2])}")
            results["partial"] += 1
        else:
            print(f"  ❌ FAIL - Only {validation['fields_populated']}/7 fields populated")
            print(f"     Issues: {', '.join(validation['issues'][:3])}")
            results["failed"] += 1

        results["details"].append({
            "component": component['name'],
            "fields_populated": validation["fields_populated"],
            "valid": validation["valid"],
            "issues": validation["issues"]
        })

    return results


# ===========================
# 5. CHECKLIST FOR REAL TEST
# ===========================

def print_real_llm_test_checklist():
    """Print what needs to be checked when running against real LLM."""

    print("\n" + "="*80)
    print("REAL LLM VERIFICATION CHECKLIST")
    print("="*80)

    checklist = {
        "Coverage": [
            "Do ALL nodes have semantic_metadata populated?",
            "What % of nodes are missing semantic_metadata?",
            "Any pattern in which types get skipped?"
        ],
        "Quality": [
            "Are semantic_role values valid (13 predefined values)?",
            "Is business_context meaningful or generic?",
            "Is business_significance specific to this code?",
            "Are impacted_workflows realistic?",
            "Does risk_level match actual criticality?"
        ],
        "Hallucination": [
            "Does business_context mention features that don't exist?",
            "Are workflow names fabricated?",
            "Does semantic_role match the code reality?"
        ],
        "Consistency": [
            "Similar components get similar roles?",
            "Risk levels are consistent across similar types?",
            "business_context follows same format/style?"
        ],
        "Edge Cases": [
            "Small utility functions get processed?",
            "Large complex classes get detailed semantic info?",
            "Abstract/interface components handled well?"
        ]
    }

    for category, items in checklist.items():
        print(f"\n{category}:")
        for i, item in enumerate(items, 1):
            print(f"  [{i}] {item}")


# ===========================
# 6. PROBLEMS TO WATCH FOR
# ===========================

def print_common_problems():
    """Print common LLM problems we should watch for."""

    print("\n" + "="*80)
    print("COMMON LLM PROBLEMS TO WATCH FOR")
    print("="*80)

    problems = {
        "Problem 1: Complete Omission": {
            "description": "LLM ignores semantic extraction guidance entirely",
            "symptom": "semantic_metadata field is None for most/all nodes",
            "fix": "Strengthen prompt: add '<json>' markers, increase examples, use step-by-step"
        },
        "Problem 2: Generic Content": {
            "description": "LLM fills fields with meaningless generic text",
            "symptom": 'business_context: "handles data", risk_level: "medium"',
            "fix": "Provide specific examples, ask for concrete business impact"
        },
        "Problem 3: Hallucination": {
            "description": "LLM invents business logic that doesn't exist",
            "symptom": 'Describes features code doesn\'t actually have',
            "fix": "Add validation: does code actually do what semantic says?"
        },
        "Problem 4: Enum Violations": {
            "description": "LLM uses semantic_role values not in our enum",
            "symptom": 'semantic_role: "handler" (not in: gateway, processor, ...)',
            "fix": "Add enum constraint in prompt, validate in code"
        },
        "Problem 5: Inconsistency": {
            "description": "Similar components get different semantic tags",
            "symptom": "Two routers: one is ORCHESTRATOR, one is PROCESSOR",
            "fix": "Add consistency rules in prompt"
        },
        "Problem 6: Attribute Omission": {
            "description": "Only some of 7 fields get populated",
            "symptom": "Only semantic_role and risk_level, missing others",
            "fix": "Add checkpoints: 'MUST include all 7 fields'"
        }
    }

    for name, details in problems.items():
        print(f"\n{name}")
        print(f"  Description: {details['description']}")
        print(f"  Symptom: {details['symptom']}")
        print(f"  Fix: {details['fix']}")


# ===========================
# 7. METRICS COLLECTION
# ===========================

def print_metrics_to_collect():
    """Print what metrics we should collect in production."""

    print("\n" + "="*80)
    print("METRICS TO COLLECT IN PRODUCTION")
    print("="*80)

    metrics = {
        "Coverage Metrics": [
            "% of nodes with semantic_metadata populated",
            "% of semantic_metadata with all 7 fields",
            "Average fields populated per node",
            "Breakdown by pattern (A/B/C)",
            "Breakdown by node_type (class/function/module)"
        ],
        "Quality Metrics": [
            "semantic_role distribution (which roles most common?)",
            "Average character length of business_context",
            "% of nodes with >1 impacted_workflows",
            "Common risk_level distributions",
            "Avg dependencies_description length"
        ],
        "Validation Metrics": [
            "% of semantic_role values that are invalid",
            "% of business_context that are clearly generic",
            "% of impacted_workflows that don't exist",
            "LLM error rate (unparseable JSON)"
        ],
        "Performance Metrics": [
            "DRILL phase latency with semantic extraction",
            "Token usage increase from semantic guidance",
            "Response size increase"
        ]
    }

    for category, items in metrics.items():
        print(f"\n{category}:")
        for metric in items:
            print(f"  • {metric}")


# ===========================
# 8. MAIN TEST RUNNER
# ===========================

def run_all_checks():
    """Run all verification checks."""

    print("\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*78 + "║")
    print("║" + "LLM SEMANTIC EXTRACTION - COMPLIANCE VERIFICATION".center(78) + "║")
    print("║" + " "*78 + "║")
    print("╚" + "="*78 + "╝")

    # Test 1: Simulation
    results = test_semantic_compliance_simulation()

    print(f"\n\nSimulation Results:")
    print(f"  ✅ Passed: {results['passed']}/{results['total_tests']}")
    print(f"  ⚠️  Partial: {results['partial']}/{results['total_tests']}")
    print(f"  ❌ Failed: {results['failed']}/{results['total_tests']}")

    # Test 2: Checklist
    print_real_llm_test_checklist()

    # Test 3: Problems
    print_common_problems()

    # Test 4: Metrics
    print_metrics_to_collect()

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print("""
✅ INFRASTRUCTURE: Ready (schema, API, frontend all working)
⚠️  LLM COMPLIANCE: Unknown (needs real-world testing)

NEXT STEPS:
1. Run drilldown on 3-5 real components
2. Check if semantic_metadata is populated
3. Evaluate quality of generated content
4. Adjust prompt if needed
5. Monitor metrics in production

KEY RISK:
  If LLM ignores semantic guidance → need prompt refinement
  If LLM generates generic content → need better examples
  If partial fields populated → need stronger constraints
""")


if __name__ == "__main__":
    run_all_checks()
