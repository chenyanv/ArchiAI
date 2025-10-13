#!/usr/bin/env python3
"""
Utility for loading the generated call graph JSON into a NetworkX directed graph.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable

import networkx as nx


def load_graph_from_json(json_path: str) -> nx.DiGraph:
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

    graph = nx.DiGraph(name=path.stem)

    nodes_data: Iterable[Dict[str, Any]] = graph_data.get("nodes", [])
    missing_ids = 0
    for node_info in nodes_data:
        node_id = node_info.get("id")
        if not node_id:
            missing_ids += 1
            continue
        attrs = {key: value for key, value in node_info.items() if key != "id"}
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
        graph.add_edge(source, target, **attrs)

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


def sanity_check(graph: nx.DiGraph, test_node: str, limit: int = 5) -> None:
    """
    Print a lightweight sanity check summary for ``test_node``.
    """
    if not test_node:
        print("\n未提供测试节点，跳过健全性检查。")
        return

    print("\n--- 开始进行健全性检查 ---")
    if graph.has_node(test_node):
        print(f"✅ 成功找到测试节点: {test_node}")
        callees = list(graph.successors(test_node))
        callers = list(graph.predecessors(test_node))
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
