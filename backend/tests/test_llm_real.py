"""
Real LLM Testing - Actually call the LLM to verify semantic extraction works.

Run this AFTER deploying to get real-world validation.

Usage:
    python tests/test_llm_real.py --api-key YOUR_GEMINI_KEY --num-tests 5
"""

import json
import sys
from pathlib import Path
from typing import Optional, List
import argparse

sys.path.insert(0, str(Path(__file__).parent.parent))

# ===========================
# REAL TEST COMPONENTS
# ===========================

REALISTIC_COMPONENTS = [
    {
        "name": "REST API Gateway",
        "file": "api/gateway.py",
        "code": """
class APIGateway:
    '''Main REST API entry point for all external clients.'''

    def __init__(self, config: Config):
        self.router = Router()
        self.auth = AuthMiddleware()
        self.logger = Logger()
        self.cache = RedisCache()

    async def handle_request(self, request: Request) -> Response:
        '''Process incoming HTTP request.'''
        self.logger.info(f"Request: {request.method} {request.path}")

        # Auth check
        if not self.auth.verify(request):
            return Response(status=401)

        # Check cache
        if cached := self.cache.get(request.path):
            return cached

        # Route to handler
        handler = self.router.find(request.path)
        if not handler:
            return Response(status=404)

        result = await handler(request)
        self.cache.set(request.path, result)
        return result

    def register_route(self, method: str, path: str, handler):
        self.router.register(method, path, handler)
""",
        "expected_role": "GATEWAY or PROCESSOR",
        "description": "Main API entry point handling all HTTP requests"
    },
    {
        "name": "Data Validation Pipeline",
        "file": "processing/validator.py",
        "code": """
class ValidationPipeline:
    '''Multi-stage data quality validation.'''

    def __init__(self):
        self.rules = []
        self.error_handler = ErrorHandler()

    def add_rule(self, rule: ValidationRule):
        self.rules.append(rule)

    def validate(self, data: Dict) -> ValidationResult:
        '''Run all validation rules on input data.'''
        errors = []

        for rule in self.rules:
            try:
                if not rule.check(data):
                    errors.append(rule.error_message)
            except Exception as e:
                self.error_handler.log(e)
                errors.append(f"Validation error: {str(e)}")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            timestamp=datetime.now()
        )

    def get_report(self, results: List[ValidationResult]) -> Report:
        '''Generate validation report for batch.'''
        return Report(
            total=len(results),
            valid=sum(1 for r in results if r.valid),
            error_rate=(sum(1 for r in results if not r.valid) / len(results))
        )
""",
        "expected_role": "VALIDATOR or PROCESSOR",
        "description": "Quality assurance for data processing pipeline"
    },
    {
        "name": "Document Storage Repository",
        "file": "persistence/document_repo.py",
        "code": """
class DocumentRepository:
    '''Manages persistent storage and retrieval of documents.'''

    def __init__(self, db_connection: DatabaseConnection):
        self.db = db_connection
        self.cache = LocalCache()
        self.indexer = SearchIndexer()

    async def save(self, document: Document) -> str:
        '''Save document to persistent storage.'''
        # Validate before save
        if not document.validate():
            raise ValueError("Invalid document")

        # Store in database
        doc_id = self.db.insert('documents', {
            'title': document.title,
            'content': document.content,
            'metadata': document.metadata,
            'created_at': datetime.now()
        })

        # Update search index
        self.indexer.add(doc_id, document.title, document.content)

        return doc_id

    async def find_by_id(self, doc_id: str) -> Optional[Document]:
        '''Retrieve document by ID.'''
        if cached := self.cache.get(doc_id):
            return cached

        row = self.db.select('documents', id=doc_id)
        if not row:
            return None

        doc = Document.from_row(row)
        self.cache.set(doc_id, doc)
        return doc

    async def search(self, query: str) -> List[Document]:
        '''Full-text search across documents.'''
        doc_ids = self.indexer.search(query)
        return [await self.find_by_id(id) for id in doc_ids]
""",
        "expected_role": "REPOSITORY or STORAGE",
        "description": "Persistence layer for document management"
    },
]


# ===========================
# TEST HARNESS
# ===========================

def create_drill_prompt(component: dict) -> str:
    """Create the DRILL phase prompt for semantic extraction."""
    return f"""You are analyzing a software component for semantic meaning.

Component: {component['name']}
File: {component['file']}
Purpose: {component['description']}

Code:
```python
{component['code']}
```

Analyze this component and provide EXACTLY these 7 semantic fields:

1. semantic_role - What role does this play? (gateway, processor, validator, transformer, repository, factory, adapter, orchestrator, mediator, aggregator, dispatcher, strategy, sink)
2. business_context - What does this do for the business? (NOT technical details)
3. business_significance - Why is this important? What breaks if it fails?
4. flow_position - Where in workflows? (entry_point, validation, processing, transformation, aggregation, storage, output, error_handling)
5. risk_level - Business impact if broken? (critical, high, medium, low)
6. impacted_workflows - Which business workflows use this? (array)
7. dependencies_description - What does this need to function?

CRITICAL: Respond with ONLY valid JSON, no other text:

{{
  "semantic_role": "<one-of-13-roles>",
  "business_context": "<business-meaning>",
  "business_significance": "<why-matters>",
  "flow_position": "<flow-stage>",
  "risk_level": "<criticality>",
  "impacted_workflows": ["<workflow1>", "<workflow2>"],
  "dependencies_description": "<external-deps>"
}}"""


def test_with_gemini_api(api_key: str, num_tests: int = 3):
    """Test semantic extraction with real Gemini API."""
    try:
        import google.generativeai as genai
    except ImportError:
        print("❌ google-generativeai not installed")
        print("   Install: pip install google-generativeai")
        return None

    print("\n" + "="*80)
    print("REAL LLM SEMANTIC EXTRACTION TEST")
    print("="*80)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-pro")

    results = {
        "total": min(num_tests, len(REALISTIC_COMPONENTS)),
        "successful_parses": 0,
        "semantic_compliance": 0,
        "details": []
    }

    for i, component in enumerate(REALISTIC_COMPONENTS[:num_tests]):
        print(f"\n[{i+1}/{results['total']}] Testing: {component['name']}")

        try:
            prompt = create_drill_prompt(component)

            response = model.generate_content(prompt)
            response_text = response.text

            print(f"  LLM Response: {response_text[:100]}...")

            # Try to parse JSON
            try:
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1

                if json_start == -1:
                    print(f"  ❌ No JSON found in response")
                    results["details"].append({
                        "component": component['name'],
                        "status": "parse_failed",
                        "reason": "no_json"
                    })
                    continue

                json_str = response_text[json_start:json_end]
                data = json.loads(json_str)

                results["successful_parses"] += 1

                # Validate semantic compliance
                required_fields = [
                    'semantic_role',
                    'business_context',
                    'business_significance',
                    'flow_position',
                    'risk_level',
                    'impacted_workflows',
                    'dependencies_description'
                ]

                missing_fields = [f for f in required_fields if not data.get(f)]

                if len(missing_fields) == 0:
                    print(f"  ✅ PASS - All 7 fields populated")
                    results["semantic_compliance"] += 1
                    status = "pass"
                elif len(missing_fields) <= 2:
                    print(f"  ⚠️  PARTIAL - Missing: {', '.join(missing_fields)}")
                    status = "partial"
                else:
                    print(f"  ❌ FAIL - Missing {len(missing_fields)} fields")
                    status = "incomplete"

                results["details"].append({
                    "component": component['name'],
                    "status": status,
                    "semantic_data": data,
                    "missing_fields": missing_fields
                })

            except json.JSONDecodeError as e:
                print(f"  ❌ Invalid JSON: {e}")
                results["details"].append({
                    "component": component['name'],
                    "status": "invalid_json",
                    "error": str(e)
                })

        except Exception as e:
            print(f"  ❌ API Error: {e}")
            results["details"].append({
                "component": component['name'],
                "status": "api_error",
                "error": str(e)
            })

    # Print summary
    print("\n" + "="*80)
    print("RESULTS SUMMARY")
    print("="*80)
    print(f"Total Tests: {results['total']}")
    print(f"Successful Parses: {results['successful_parses']}/{results['total']}")
    print(f"Full Compliance: {results['semantic_compliance']}/{results['total']}")

    return results


def test_with_claude_api(api_key: str, num_tests: int = 3):
    """Test semantic extraction with Claude API."""
    try:
        from anthropic import Anthropic
    except ImportError:
        print("❌ anthropic not installed")
        print("   Install: pip install anthropic")
        return None

    print("\n" + "="*80)
    print("REAL LLM SEMANTIC EXTRACTION TEST - CLAUDE")
    print("="*80)

    client = Anthropic(api_key=api_key)

    results = {
        "total": min(num_tests, len(REALISTIC_COMPONENTS)),
        "successful_parses": 0,
        "semantic_compliance": 0,
        "details": []
    }

    for i, component in enumerate(REALISTIC_COMPONENTS[:num_tests]):
        print(f"\n[{i+1}/{results['total']}] Testing: {component['name']}")

        try:
            prompt = create_drill_prompt(component)

            message = client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text
            print(f"  Claude Response: {response_text[:100]}...")

            # Try to parse JSON
            try:
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1

                if json_start == -1:
                    print(f"  ❌ No JSON found in response")
                    results["details"].append({
                        "component": component['name'],
                        "status": "parse_failed",
                        "reason": "no_json"
                    })
                    continue

                json_str = response_text[json_start:json_end]
                data = json.loads(json_str)

                results["successful_parses"] += 1

                # Validate semantic compliance
                required_fields = [
                    'semantic_role',
                    'business_context',
                    'business_significance',
                    'flow_position',
                    'risk_level',
                    'impacted_workflows',
                    'dependencies_description'
                ]

                missing_fields = [f for f in required_fields if not data.get(f)]

                if len(missing_fields) == 0:
                    print(f"  ✅ PASS - All 7 fields populated")
                    results["semantic_compliance"] += 1
                    status = "pass"
                elif len(missing_fields) <= 2:
                    print(f"  ⚠️  PARTIAL - Missing: {', '.join(missing_fields)}")
                    status = "partial"
                else:
                    print(f"  ❌ FAIL - Missing {len(missing_fields)} fields")
                    status = "incomplete"

                results["details"].append({
                    "component": component['name'],
                    "status": status,
                    "semantic_data": data,
                    "missing_fields": missing_fields
                })

            except json.JSONDecodeError as e:
                print(f"  ❌ Invalid JSON: {e}")
                results["details"].append({
                    "component": component['name'],
                    "status": "invalid_json",
                    "error": str(e)
                })

        except Exception as e:
            print(f"  ❌ API Error: {e}")
            results["details"].append({
                "component": component['name'],
                "status": "api_error",
                "error": str(e)
            })

    # Print summary
    print("\n" + "="*80)
    print("RESULTS SUMMARY")
    print("="*80)
    print(f"Total Tests: {results['total']}")
    print(f"Successful Parses: {results['successful_parses']}/{results['total']}")
    print(f"Full Compliance: {results['semantic_compliance']}/{results['total']}")

    return results


# ===========================
# CLI INTERFACE
# ===========================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test real LLM semantic extraction")
    parser.add_argument("--gemini-key", help="Google Gemini API key")
    parser.add_argument("--claude-key", help="Claude API key")
    parser.add_argument("--num-tests", type=int, default=3, help="Number of tests to run")

    args = parser.parse_args()

    if not args.gemini_key and not args.claude_key:
        print("Usage:")
        print("  python test_llm_real.py --gemini-key YOUR_KEY [--num-tests 3]")
        print("  python test_llm_real.py --claude-key YOUR_KEY [--num-tests 3]")
        print("\nNo API key provided. See instructions above.")
        sys.exit(1)

    if args.gemini_key:
        test_with_gemini_api(args.gemini_key, args.num_tests)

    if args.claude_key:
        test_with_claude_api(args.claude_key, args.num_tests)
