from __future__ import annotations

from dataclasses import dataclass, field
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
