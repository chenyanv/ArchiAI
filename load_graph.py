#!/usr/bin/env python3
"""
Utility for loading the generated call graph JSON into a NetworkX directed graph.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List

import networkx as nx


_FALLBACK_ROOT_CATEGORY_MAP: Dict[str, str] = {
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
    "workflow": "service",
    "workflows": "service",
}

_FALLBACK_UTILITY_KEYWORDS: tuple[str, ...] = (
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

_FALLBACK_SERVICE_KEYWORDS: tuple[str, ...] = (
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

_FALLBACK_CONTROLLER_KEYWORDS: tuple[str, ...] = (
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

_FALLBACK_MODEL_KEYWORDS: tuple[str, ...] = (
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

_FALLBACK_PIPELINE_KEYWORDS: tuple[str, ...] = (
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

_FALLBACK_INTEGRATION_KEYWORDS: tuple[str, ...] = (
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

_FALLBACK_SDK_KEYWORDS: tuple[str, ...] = (
    "sdk",
    "client",
    "clients",
    "api_client",
)

_FALLBACK_INFRASTRUCTURE_KEYWORDS: tuple[str, ...] = (
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

_FALLBACK_TEST_KEYWORDS: tuple[str, ...] = (
    "test",
    "tests",
    "testing",
    "fixture",
    "fixtures",
)

_FALLBACK_SERVICE_SUFFIXES: tuple[str, ...] = (
    "service",
    "manager",
    "workflow",
    "handler",
    "processor",
    "orchestrator",
    "usecase",
)

_FALLBACK_CONTROLLER_SUFFIXES: tuple[str, ...] = (
    "controller",
    "router",
    "endpoint",
    "view",
)

_FALLBACK_MODEL_SUFFIXES: tuple[str, ...] = (
    "model",
    "entity",
    "schema",
    "record",
    "document",
    "dto",
)

_FALLBACK_INTEGRATION_SUFFIXES: tuple[str, ...] = (
    "connector",
    "adapter",
    "integration",
    "hook",
    "provider",
)

_FALLBACK_SDK_SUFFIXES: tuple[str, ...] = (
    "client",
    "sdk",
)


def _contains_any(values: Iterable[str], keywords: Iterable[str]) -> bool:
    for value in values:
        lowered = value.lower()
        for keyword in keywords:
            if keyword in lowered:
                return True
    return False


def _tokenise_name(value: str) -> List[str]:
    lowered = value.lower()
    tokens = [lowered]
    tokens.extend(
        segment for segment in lowered.replace("-", "_").split("_") if segment
    )
    return tokens


def _has_any_suffix(tokens: Iterable[str], suffixes: Iterable[str]) -> bool:
    for token in tokens:
        for suffix in suffixes:
            if token.endswith(suffix):
                return True
    return False


def _infer_node_category(node_id: str, attrs: Dict[str, Any]) -> str:
    category = attrs.get("category")
    if isinstance(category, str) and category:
        return category

    kind = attrs.get("kind")
    if kind == "external_call":
        return "external"
    if isinstance(node_id, str) and node_id.startswith("external::"):
        return "external"

    path_raw = str(attrs.get("file_path") or "")
    path_obj = PurePosixPath(path_raw.replace("\\", "/"))
    path_parts = tuple(part.lower() for part in path_obj.parts if part)
    joined_path = "/".join(path_parts)

    class_name = str(attrs.get("class_name") or "")
    function_name = str(attrs.get("function_name") or "")
    name_tokens = _tokenise_name(class_name) + _tokenise_name(function_name)

    if _contains_any(path_parts, _FALLBACK_TEST_KEYWORDS) or joined_path.startswith("tests") or joined_path.endswith("test.py"):
        return "test"
    if any(token.startswith("test") for token in name_tokens):
        return "test"

    if path_parts:
        root_category = _FALLBACK_ROOT_CATEGORY_MAP.get(path_parts[0])
        if root_category:
            return root_category

    if _contains_any(path_parts, _FALLBACK_UTILITY_KEYWORDS) or _contains_any(name_tokens, _FALLBACK_UTILITY_KEYWORDS):
        return "utility"

    if _contains_any(path_parts, _FALLBACK_INFRASTRUCTURE_KEYWORDS) or _contains_any(name_tokens, ("config", "settings", "provider")):
        return "infrastructure"

    if _contains_any(path_parts, _FALLBACK_CONTROLLER_KEYWORDS) or _has_any_suffix(name_tokens, _FALLBACK_CONTROLLER_SUFFIXES):
        return "controller"

    if _contains_any(path_parts, _FALLBACK_SERVICE_KEYWORDS) or _has_any_suffix(name_tokens, _FALLBACK_SERVICE_SUFFIXES):
        return "service"

    if _contains_any(path_parts, _FALLBACK_MODEL_KEYWORDS) or _has_any_suffix(name_tokens, _FALLBACK_MODEL_SUFFIXES):
        return "model"

    if _contains_any(path_parts, _FALLBACK_PIPELINE_KEYWORDS):
        return "data_pipeline"

    if _contains_any(path_parts, _FALLBACK_INTEGRATION_KEYWORDS) or _has_any_suffix(name_tokens, _FALLBACK_INTEGRATION_SUFFIXES):
        return "integration"

    if path_parts and path_parts[0] == "sdk":
        return "sdk"
    if _contains_any(path_parts, _FALLBACK_SDK_KEYWORDS) or _has_any_suffix(name_tokens, _FALLBACK_SDK_SUFFIXES):
        return "sdk"

    return "implementation"


DEFAULT_EDGE_WEIGHT = 1.0

CATEGORY_WEIGHTS: Dict[str, float] = {
    "controller": 1.8,
    "data_pipeline": 0.12,
    "external": 0.0,
    "implementation": 1.0,
    "infrastructure": 0.2,
    "integration": 0.1,
    "model": 1.3,
    "sdk": 0.45,
    "service": 2.0,
    "test": 0.0,
    "unknown": 0.85,
    "utility": 0.08,
}

SOURCE_CATEGORY_MODIFIERS: Dict[str, float] = {
    "controller": 1.1,
    "data_pipeline": 0.4,
    "external": 0.0,
    "infrastructure": 0.8,
    "integration": 0.85,
    "model": 1.05,
    "sdk": 0.85,
    "service": 1.15,
    "test": 0.0,
    "utility": 0.6,
}

FILE_NODE_WEIGHT_CAP = 0.35
LOGGING_WEIGHT_CAP = 0.03

_LOGGING_PREFIXES: tuple[str, ...] = (
    "logger.",
    "logging.",
    "loguru.",
    "metrics.",
    "telemetry.",
    "statsd.",
    "sentry.",
    "sentry_sdk.",
    "opentelemetry.",
    "tracer.",
    "trace.",
    "meter.",
    "prometheus.",
    "warnings.",
)

_LOGGING_SUFFIXES: tuple[str, ...] = (
    ".debug",
    ".info",
    ".warning",
    ".warn",
    ".error",
    ".exception",
    ".critical",
    ".trace",
)

_LOGGING_TOKENS: tuple[str, ...] = (
    "debug",
    "info",
    "warning",
    "warn",
    "error",
    "exception",
    "critical",
    "metric",
    "gauge",
    "timer",
    "span",
    "event",
    "record",
)

_NOISY_CALL_NAMES: tuple[str, ...] = (
    "print",
    "pprint.pprint",
)


def _normalise_category(node_data: Dict[str, Any]) -> str:
    category = node_data.get("category") or node_data.get("kind") or "unknown"
    if isinstance(category, str) and category:
        return category
    return "unknown"


def _is_logging_or_metric_call(call_name: str) -> bool:
    if not call_name:
        return False
    lowered = call_name.lower()
    if lowered in _NOISY_CALL_NAMES:
        return True
    if any(lowered.startswith(prefix) for prefix in _LOGGING_PREFIXES):
        return True
    if any(lowered.endswith(suffix) for suffix in _LOGGING_SUFFIXES):
        return True
    token = lowered.rsplit(".", 1)[-1]
    if lowered.startswith(("logger", "logging", "metrics", "telemetry", "statsd", "sentry", "sentry_sdk", "opentelemetry", "tracer", "meter", "prometheus", "warnings")) and token in _LOGGING_TOKENS:
        return True
    return False


def _compute_edge_weight(
    graph: nx.MultiDiGraph,
    source: str,
    target: str,
    attrs: Dict[str, Any],
) -> float:
    edge_type = attrs.get("type")
    if edge_type != "CALLS":
        return 0.0

    source_data = graph.nodes.get(source, {})
    target_data = graph.nodes.get(target, {})

    source_category = _normalise_category(source_data)
    target_category = _normalise_category(target_data)

    if "test" in {source_category, target_category}:
        return 0.0

    base_weight = CATEGORY_WEIGHTS.get(
        target_category,
        CATEGORY_WEIGHTS.get("implementation", DEFAULT_EDGE_WEIGHT),
    )
    source_modifier = SOURCE_CATEGORY_MODIFIERS.get(source_category, 1.0)

    weight = base_weight * source_modifier

    if target_data.get("kind") == "file":
        weight = min(weight, FILE_NODE_WEIGHT_CAP)

    call_sites = attrs.get("call_sites") or []
    call_name = ""
    if call_sites:
        first = call_sites[0]
        if isinstance(first, dict):
            call_name = str(first.get("expression", "")).lower()
        else:
            call_name = str(first).lower()

    if _is_logging_or_metric_call(call_name):
        weight = min(weight, LOGGING_WEIGHT_CAP)

    if attrs.get("resolved") is False:
        weight = 0.0

    return max(weight, 0.0)


def load_graph_from_json(json_path: str) -> nx.MultiDiGraph:
    """
    Load the call graph stored in ``json_path`` into a NetworkX DiGraph.

    The JSON is expected to contain ``nodes`` and ``edges`` collections as produced
    by the structural scaffolding pipeline. Optional keys (such as
    ``unresolved_calls``) are stored on ``graph.graph`` for later inspection.
    """
    path = Path(json_path)
    print(f"开始从 {path} 加载图数据...")
    start_time = time.perf_counter()

    if not path.exists():
        raise FileNotFoundError(f"未找到图数据文件: {path}")

    with path.open("r", encoding="utf-8") as fp:
        graph_data: Dict[str, Any] = json.load(fp)

    graph = nx.MultiDiGraph(name=path.stem)

    nodes_data: Iterable[Dict[str, Any]] = graph_data.get("nodes", [])
    missing_ids = 0
    for node_info in nodes_data:
        node_id = node_info.get("id")
        if not node_id:
            missing_ids += 1
            continue
        attrs = {key: value for key, value in node_info.items() if key != "id"}
        if not attrs.get("category"):
            attrs["category"] = _infer_node_category(node_id, attrs)
        graph.add_node(node_id, **attrs)

    edges_data: Iterable[Dict[str, Any]] = graph_data.get("edges", [])
    skipped_edges = 0
    for edge_info in edges_data:
        source = edge_info.get("source")
        target = edge_info.get("target")
        if not source or not target:
            skipped_edges += 1
            continue
        attrs = {
            key: value
            for key, value in edge_info.items()
            if key not in {"source", "target"}
        }
        edge_type = attrs.get("type") or "UNKNOWN"
        attrs["type"] = edge_type
        weight = _compute_edge_weight(graph, source, target, attrs)
        attrs["weight"] = weight
        existing = graph.get_edge_data(source, target) or {}
        key = edge_type
        suffix = 1
        while key in existing:
            key = f"{edge_type}:{suffix}"
            suffix += 1
        graph.add_edge(source, target, key=key, **attrs)

    unresolved_calls = graph_data.get("unresolved_calls")
    if unresolved_calls is not None:
        graph.graph["unresolved_calls"] = unresolved_calls

    elapsed = time.perf_counter() - start_time
    print("--- 图加载完成！---")
    print(f"图中有 {graph.number_of_nodes()} 个节点。")
    print(f"图中有 {graph.number_of_edges()} 条边。")
    if missing_ids:
        print(f"警告: 跳过了 {missing_ids} 个缺少 id 的节点。")
    if skipped_edges:
        print(f"警告: 跳过了 {skipped_edges} 条缺少端点的边。")
    if unresolved_calls is not None:
        print(f"记录了 {len(unresolved_calls)} 个未解析的调用。")
    print(f"加载过程耗时: {elapsed:.2f} 秒。")

    return graph


def sanity_check(graph: nx.MultiDiGraph, test_node: str, limit: int = 5) -> None:
    """
    Print a lightweight sanity check summary for ``test_node``.
    """
    if not test_node:
        print("\n未提供测试节点，跳过健全性检查。")
        return

    print("\n--- 开始进行健全性检查 ---")
    if graph.has_node(test_node):
        print(f"✅ 成功找到测试节点: {test_node}")
        callees: List[str] = []
        for neighbor in graph.successors(test_node):
            edge_data = graph.get_edge_data(test_node, neighbor)
            if not edge_data:
                continue
            attrs_iter = edge_data.values() if graph.is_multigraph() else [edge_data]
            if any(attrs.get("type") == "CALLS" for attrs in attrs_iter):
                callees.append(neighbor)

        callers: List[str] = []
        for neighbor in graph.predecessors(test_node):
            edge_data = graph.get_edge_data(neighbor, test_node)
            if not edge_data:
                continue
            attrs_iter = edge_data.values() if graph.is_multigraph() else [edge_data]
            if any(attrs.get("type") == "CALLS" for attrs in attrs_iter):
                callers.append(neighbor)
        print(f"   -> 它调用了 ({len(callees)} 个): {callees[:limit]}")
        print(f"   -> 它被 ({len(callers)} 个) 调用: {callers[:limit]}")
    else:
        print(f"❌ 未找到测试节点: {test_node}。请检查 JSON 数据和节点 ID。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从 call_graph.json 构建 NetworkX 有向图。"
    )
    parser.add_argument(
        "--json",
        default="results/graphs/call_graph.json",
        help="指向 call_graph.json 的路径 (默认: %(default)s)",
    )
    parser.add_argument(
        "--test-node",
        default="python::intergrations/firecrawl/firecrawl_connector.py::FirecrawlConnector::_make_request",
        help="用于健全性检查的节点 ID。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="打印邻居列表时展示的最大数量。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    graph = load_graph_from_json(args.json)
    sanity_check(graph, args.test_node, args.limit)


if __name__ == "__main__":
    main()
