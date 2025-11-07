#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.find_paths import build_find_paths_tool  # noqa: E402
from tools.graph_queries import DEFAULT_GRAPH_PATH  # noqa: E402

PRESETS = {
    "structural": {
        "start": ["python::file::agentic_reasoning/deep_research.py"],
        "end": [
            "python::agentic_reasoning/deep_research.py::DeepResearcher::_generate_reasoning"
        ],
        "edge_types": ["CONTAINS"],
        "max_depth": 4,
        "description": "文件 -> 类 -> 方法 的结构路径",
    },
    "call": {
        "start": [
            "python::intergrations/firecrawl/firecrawl_ui.py::FirecrawlUIBuilder::create_ui_schema"
        ],
        "end": [
            "python::intergrations/firecrawl/firecrawl_ui.py::FirecrawlUIBuilder::create_data_source_config"
        ],
        "edge_types": ["CALLS"],
        "max_depth": 3,
        "description": "Firecrawl UI builder 内部的调用链",
    },
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trace paths across ragflow-main nodes using the find_paths tool.",
    )
    parser.add_argument(
        "--preset",
        choices=tuple(PRESETS.keys()),
        default="structural",
        help="内置场景，structural 展示 CONTAINS，call 展示 CALLS。",
    )
    parser.add_argument(
        "--start",
        nargs="+",
        default=None,
        help="Override the start nodes (defaults to the selected preset).",
    )
    parser.add_argument(
        "--end",
        nargs="+",
        default=None,
        help="Override the end nodes (defaults to the selected preset).",
    )
    parser.add_argument(
        "--edge-types",
        nargs="+",
        default=None,
        help="Edge types to allow (defaults to the selected preset).",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="Maximum hops (defaults to the selected preset).",
    )
    parser.add_argument(
        "--graph",
        type=Path,
        default=None,
        help="Optional override for the call graph JSON path.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    tool = build_find_paths_tool(args.graph or DEFAULT_GRAPH_PATH)
    preset = PRESETS[args.preset]
    start_nodes = args.start or preset["start"]
    end_nodes = args.end or preset["end"]
    edge_types = args.edge_types or preset["edge_types"]
    max_depth = args.max_depth or preset["max_depth"]
    payload = {
        "start_nodes": start_nodes,
        "end_nodes": end_nodes,
        "edge_types": edge_types,
        "max_depth": max_depth,
    }
    print(
        f"# 预设: {args.preset} -> {preset['description']} "
        f"(edge_types={edge_types}, max_depth={max_depth})"
    )
    result = tool.invoke(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
