from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, MutableMapping, Sequence, Set

import networkx as nx

from structural_scaffolding.models import Profile
from structural_scaffolding.parsing import sanitize_call_name


@dataclass(slots=True)
class CallGraph:
    """Container around a NetworkX directed graph representing intra-repository calls."""

    graph: nx.DiGraph
    """Directed graph whose nodes are profile identifiers and edges represent call sites."""
    unresolved_calls: Set[str] = field(default_factory=set)
    """Names of calls that could not be resolved to a known profile."""

    def to_edge_index(self) -> List[Dict[str, str]]:
        """Return a serialisable list of edges with core attributes."""
        return [
            {
                "source": source,
                "target": target,
                "call": data.get("call", ""),
                "resolved": bool(data.get("resolved", False)),
            }
            for source, target, data in self.graph.edges(data=True)
        ]


_ROOT_CATEGORY_MAP: Dict[str, str] = {
    "adapters": "integration",
    "adapter": "integration",
    "apis": "controller",
    "api": "controller",
    "apps": "controller",
    "clients": "sdk",
    "client": "sdk",
    "common": "utility",
    "configs": "infrastructure",
    "config": "infrastructure",
    "controller": "controller",
    "controllers": "controller",
    "dto": "model",
    "entities": "model",
    "entity": "model",
    "fixtures": "test",
    "helpers": "utility",
    "helper": "utility",
    "infra": "infrastructure",
    "infrastructure": "infrastructure",
    "integration": "integration",
    "integrations": "integration",
    "jobs": "infrastructure",
    "lib": "utility",
    "libs": "utility",
    "model": "model",
    "models": "model",
    "ops": "infrastructure",
    "pipeline": "data_pipeline",
    "pipelines": "data_pipeline",
    "plugin": "integration",
    "plugins": "integration",
    "providers": "integration",
    "provider": "integration",
    "routes": "controller",
    "router": "controller",
    "routers": "controller",
    "schemas": "model",
    "schema": "model",
    "sdk": "sdk",
    "service": "service",
    "services": "service",
    "shared": "utility",
    "scripts": "utility",
    "script": "utility",
    "tasks": "infrastructure",
    "tests": "test",
    "test": "test",
    "tooling": "utility",
    "tools": "utility",
    "utils": "utility",
    "utility": "utility",
    "views": "controller",
    "workflows": "service",
    "workflow": "service",
}

_CATEGORY_PRIORITY: Dict[str, int] = {
    "external": 100,
    "test": 95,
    "service": 90,
    "controller": 85,
    "data_pipeline": 80,
    "model": 78,
    "integration": 70,
    "sdk": 65,
    "infrastructure": 60,
    "utility": 50,
    "implementation": 40,
}

_UTILITY_KEYWORDS: Sequence[str] = (
    "util",
    "utils",
    "helper",
    "helpers",
    "common",
    "shared",
    "base",
    "bases",
    "mixins",
    "constants",
    "types",
    "tool",
    "toolbox",
)

_INTEGRATION_KEYWORDS: Sequence[str] = (
    "integration",
    "intergration",
    "connector",
    "connectors",
    "adapter",
    "adapters",
    "webhook",
    "webhooks",
    "plugin",
    "plugins",
    "thirdparty",
    "third_party",
    "provider",
    "providers",
)

_SDK_KEYWORDS: Sequence[str] = (
    "sdk",
    "client",
    "clients",
    "api_client",
)

_SERVICE_KEYWORDS: Sequence[str] = (
    "service",
    "services",
    "usecase",
    "use_case",
    "usecases",
    "workflow",
    "workflows",
    "manager",
    "managers",
    "orchestrator",
    "orchestrators",
    "handler",
    "handlers",
    "processor",
    "processors",
)

_CONTROLLER_KEYWORDS: Sequence[str] = (
    "controller",
    "controllers",
    "router",
    "routers",
    "route",
    "routes",
    "view",
    "views",
    "endpoint",
    "endpoints",
    "api",
)

_MODEL_KEYWORDS: Sequence[str] = (
    "model",
    "models",
    "entity",
    "entities",
    "schema",
    "schemas",
    "dto",
    "document",
    "documents",
    "record",
    "records",
    "serializer",
    "serializers",
)

_PIPELINE_KEYWORDS: Sequence[str] = (
    "pipeline",
    "pipelines",
    "ingest",
    "ingestion",
    "indexer",
    "indexing",
    "retriever",
    "retrieval",
    "etl",
    "extract",
    "loader",
    "loaders",
    "transform",
    "transforms",
    "batch",
    "stream",
)

_INFRASTRUCTURE_KEYWORDS: Sequence[str] = (
    "config",
    "configs",
    "setting",
    "settings",
    "constant",
    "constants",
    "credential",
    "credentials",
    "secret",
    "secrets",
    "env",
    "environment",
    "logging",
    "logger",
    "metrics",
    "monitor",
    "monitoring",
    "db",
    "database",
    "databases",
    "migrations",
    "registry",
    "management",
    "permission",
    "permissions",
    "auth",
    "authentication",
    "authorization",
    "scheduler",
    "schedulers",
    "task",
    "tasks",
    "celery",
    "cron",
    "email",
    "notification",
    "notifications",
)

_TEST_KEYWORDS: Sequence[str] = (
    "test",
    "tests",
    "testing",
    "fixture",
    "fixtures",
)

_SERVICE_SUFFIXES: Sequence[str] = (
    "service",
    "manager",
    "workflow",
    "handler",
    "processor",
    "orchestrator",
    "usecase",
)

_CONTROLLER_SUFFIXES: Sequence[str] = (
    "controller",
    "router",
    "endpoint",
    "view",
)

_MODEL_SUFFIXES: Sequence[str] = (
    "model",
    "entity",
    "schema",
    "record",
    "document",
    "dto",
)

_INTEGRATION_SUFFIXES: Sequence[str] = (
    "connector",
    "adapter",
    "integration",
    "hook",
    "provider",
)

_SDK_SUFFIXES: Sequence[str] = (
    "client",
    "sdk",
)


def _normalise_path(path: str) -> PurePosixPath:
    return PurePosixPath(path.replace("\\", "/"))


def _contains_keyword(values: Iterable[str], keywords: Sequence[str]) -> bool:
    for value in values:
        lowered = value.lower()
        for keyword in keywords:
            if keyword in lowered:
                return True
    return False


def _collect_name_tokens(profile: Profile) -> List[str]:
    tokens: List[str] = []
    for value in (profile.class_name, profile.function_name):
        if not value:
            continue
        lowered = value.lower()
        tokens.append(lowered)
        sanitized = lowered.replace("-", "_")
        tokens.extend(segment for segment in sanitized.split("_") if segment)
    return tokens


def _has_suffix(tokens: Iterable[str], suffixes: Sequence[str]) -> bool:
    for token in tokens:
        for suffix in suffixes:
            if token.endswith(suffix):
                return True
    return False


def _profile_category(profile: Profile) -> str:
    if profile.kind == "external_call":
        return "external"

    path_obj = _normalise_path(profile.file_path or "")
    path_parts = tuple(part.lower() for part in path_obj.parts if part)
    joined_path = "/".join(path_parts)
    name_tokens = _collect_name_tokens(profile)

    scores: Dict[str, int] = defaultdict(int)
    scores["implementation"] = 1

    if not path_parts:
        return "implementation"

    # Tests & fixtures should always be deprioritised.
    if "tests/" in joined_path or joined_path.startswith("tests"):
        scores["test"] += 20
    if joined_path.endswith("test.py") or joined_path.endswith("_test.py"):
        scores["test"] += 20
    if _contains_keyword(path_parts, _TEST_KEYWORDS) or _contains_keyword(name_tokens, _TEST_KEYWORDS):
        scores["test"] += 15

    # Base category from the top-level package.
    root_category = _ROOT_CATEGORY_MAP.get(path_parts[0])
    if root_category:
        scores[root_category] += 6

    # Utility helpers across the codebase.
    if _contains_keyword(path_parts, _UTILITY_KEYWORDS) or _contains_keyword(name_tokens, _UTILITY_KEYWORDS):
        scores["utility"] += 12

    # Infrastructure/configuration modules.
    if _contains_keyword(path_parts, _INFRASTRUCTURE_KEYWORDS) or _contains_keyword(name_tokens, ("config", "settings", "provider")):
        scores["infrastructure"] += 10

    # Controllers / API surfaces.
    if path_parts[0] == "api":
        scores["controller"] += 12
    if _contains_keyword(path_parts, _CONTROLLER_KEYWORDS) or _has_suffix(name_tokens, _CONTROLLER_SUFFIXES):
        scores["controller"] += 10

    # Service layer, orchestrators, workflow managers.
    if path_parts[0] in {"agent", "agentic_reasoning"}:
        scores["service"] += 10
    if _contains_keyword(path_parts, _SERVICE_KEYWORDS) or _has_suffix(name_tokens, _SERVICE_SUFFIXES):
        scores["service"] += 10
    if "workflow" in joined_path:
        scores["service"] += 6

    # Domain models & schemas.
    if _contains_keyword(path_parts, _MODEL_KEYWORDS) or _has_suffix(name_tokens, _MODEL_SUFFIXES):
        scores["model"] += 10

    # Data pipelines & retrieval orchestration.
    if _contains_keyword(path_parts, _PIPELINE_KEYWORDS):
        scores["data_pipeline"] += 6

    # Integration boundaries.
    if _contains_keyword(path_parts, _INTEGRATION_KEYWORDS) or _has_suffix(name_tokens, _INTEGRATION_SUFFIXES):
        scores["integration"] += 9

    # SDK / client surfaces.
    if path_parts[0] == "sdk":
        scores["sdk"] += 10
    if _contains_keyword(path_parts, _SDK_KEYWORDS) or _has_suffix(name_tokens, _SDK_SUFFIXES):
        scores["sdk"] += 8

    # Sandbox and script directories are largely supportive.
    if path_parts[0] in {"sandbox", "scripts"}:
        scores["utility"] += 6

    category, _ = max(
        scores.items(),
        key=lambda item: (item[1], _CATEGORY_PRIORITY.get(item[0], 0)),
    )
    return category


def build_call_graph(profiles: Sequence[Profile]) -> CallGraph:
    """Construct a directed call graph based on extracted profiles."""
    graph = nx.DiGraph()
    filtered_profiles = [profile for profile in profiles if not _is_noisy_profile(profile)]
    alias_index = _build_alias_index(filtered_profiles)
    unresolved: Set[str] = set()

    for profile in filtered_profiles:
        graph.add_node(
            profile.id,
            kind=profile.kind,
            file_path=profile.file_path,
            function_name=profile.function_name,
            class_name=profile.class_name,
            category=_profile_category(profile),
            label=_profile_label(profile),
        )

    for profile in filtered_profiles:
        for call_expr in profile.calls:
            call = sanitize_call_name(call_expr)
            if not call or _is_noisy_call(call):
                continue
            resolved = False
            target_candidates = alias_index.get(call, set())

            if target_candidates:
                resolved = True
                for target in target_candidates:
                    graph.add_edge(
                        profile.id,
                        target,
                        call=call,
                        resolved=True,
                    )
            else:
                if _is_noisy_external_call(call):
                    continue
                unresolved.add(call)
                external_node = f"external::{call}"
                if external_node not in graph:
                    graph.add_node(
                        external_node,
                        kind="external_call",
                        category="external",
                        label=call,
                    )
                graph.add_edge(
                    profile.id,
                    external_node,
                    call=call,
                    resolved=False,
                )

    return CallGraph(graph=graph, unresolved_calls=unresolved)


def _build_alias_index(profiles: Sequence[Profile]) -> MutableMapping[str, Set[str]]:
    aliases: Dict[str, Set[str]] = {}
    for profile in profiles:
        for alias in _profile_aliases(profile):
            aliases.setdefault(alias, set()).add(profile.id)
    return aliases


_DUNDER_METHODS: Set[str] = {
    "__aenter__",
    "__aexit__",
    "__bool__",
    "__call__",
    "__contains__",
    "__del__",
    "__delitem__",
    "__enter__",
    "__eq__",
    "__exit__",
    "__format__",
    "__ge__",
    "__get__",
    "__getattr__",
    "__getattribute__",
    "__getitem__",
    "__gt__",
    "__hash__",
    "__init__",
    "__init_subclass__",
    "__iter__",
    "__le__",
    "__len__",
    "__lt__",
    "__matmul__",
    "__ne__",
    "__new__",
    "__post_init__",
    "__repr__",
    "__set__",
    "__setitem__",
    "__set_name__",
    "__setstate__",
    "__sizeof__",
    "__slots__",
    "__str__",
    "__subclasscheck__",
    "__truediv__",
}

_NOISY_MODULE_KEYWORDS: Sequence[str] = ("utils", "helper", "helpers")

_THIRD_PARTY_PREFIXES: Set[str] = {
    "aiohttp",
    "anthropic",
    "asyncio",
    "azure",
    "boto3",
    "botocore",
    "celery",
    "chromadb",
    "click",
    "cv2",
    "fastapi",
    "google",
    "httpx",
    "jinja2",
    "langchain",
    "langgraph",
    "milvus",
    "numpy",
    "openai",
    "opensearch",
    "pandas",
    "pillow",
    "pinecone",
    "psycopg",
    "pydantic",
    "redis",
    "requests",
    "rich",
    "scipy",
    "sentry_sdk",
    "sklearn",
    "sqlalchemy",
    "sqlmodel",
    "supabase",
    "tensorflow",
    "torch",
    "transformers",
    "typer",
    "uvicorn",
    "weaviate",
}


def _is_noisy_profile(profile: Profile) -> bool:
    if profile.file_path.endswith("__init__.py"):
        return True

    if profile.kind == "file":
        return False

    function_name = profile.function_name or ""
    if _is_dunder_name(function_name):
        return True
    if function_name in _DUNDER_METHODS:
        return True

    path_lower = profile.file_path.lower()
    if profile.kind in {"function", "method"} and any(keyword in path_lower for keyword in _NOISY_MODULE_KEYWORDS):
        return True

    if function_name and any(keyword in function_name.lower() for keyword in _NOISY_MODULE_KEYWORDS):
        return True

    class_name = profile.class_name or ""
    if class_name and any(keyword in class_name.lower() for keyword in _NOISY_MODULE_KEYWORDS):
        return True

    return False


def _is_noisy_call(call: str) -> bool:
    lower_call = call.lower()

    if _is_dunder_name(_call_token(call)):
        return True

    if lower_call.startswith("super(") or lower_call.startswith("super().") or lower_call.startswith("super::"):
        return True

    if any(keyword in lower_call for keyword in _NOISY_MODULE_KEYWORDS):
        return True

    for prefix in _THIRD_PARTY_PREFIXES:
        if lower_call.startswith(prefix + ".") or lower_call.startswith(prefix + "::"):
            return True

    return False


def _is_noisy_external_call(call: str) -> bool:
    return _is_noisy_call(call) or _is_dunder_name(call)


def _call_token(call: str) -> str:
    token = call.rsplit(".", 1)[-1]
    token = token.rsplit("::", 1)[-1]
    return token


def _is_dunder_name(name: str) -> bool:
    return bool(name) and name.startswith("__") and name.endswith("__")


def _profile_aliases(profile: Profile) -> Iterable[str]:
    aliases: Set[str] = set()

    def add(value: str | None) -> None:
        if value:
            alias = sanitize_call_name(value)
            if alias:
                aliases.add(alias)

    add(profile.id)
    add(profile.file_path)
    add(profile.function_name)
    add(profile.class_name)
    if profile.function_name and profile.class_name:
        add(f"{profile.class_name}.{profile.function_name}")
        add(f"{profile.class_name}::{profile.function_name}")

    return aliases


def _profile_label(profile: Profile) -> str:
    if profile.function_name and profile.class_name:
        return f"{profile.class_name}.{profile.function_name}"
    if profile.function_name:
        return profile.function_name
    if profile.class_name:
        return profile.class_name
    return profile.file_path


__all__ = ["CallGraph", "build_call_graph"]
