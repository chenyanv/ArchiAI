#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.find_relatives import build_find_relatives_tool  # noqa: E402
from tools.graph_queries import DEFAULT_GRAPH_PATH  # noqa: E402

PRESETS = {
    "descendants": {
        "node": "python::agentic_reasoning/deep_research.py::DeepResearcher",
        "relation_types": ["CONTAINS"],
        "direction": "descendants",
        "depth": 3,
        "description": "展示 DeepResearcher 类中的子方法",
    },
    "callers": {
        "node": "python::intergrations/firecrawl/firecrawl_ui.py::FirecrawlUIBuilder::create_data_source_config",
        "relation_types": ["CALLS"],
        "direction": "ancestors",
        "depth": 3,
        "description": "寻找 Firecrawl UI 配置函数的上游调用者",
    },
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview ancestor/descendant discovery for ragflow-main nodes.",
    )
    parser.add_argument(
        "--preset",
        choices=tuple(PRESETS.keys()),
        default="descendants",
        help="选择场景：descendants 查看子节点，callers 查看上游调用者。",
    )
    parser.add_argument(
        "--node",
        default=None,
        help="Override the origin node (defaults to the selected preset).",
    )
    parser.add_argument(
        "--relation-types",
        nargs="+",
        default=None,
        help="Override relation types (defaults to the selected preset).",
    )
    parser.add_argument(
        "--direction",
        choices=("descendants", "ancestors"),
        default=None,
        help="Override traversal direction (defaults to preset).",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=None,
        help="Override depth limit (defaults to preset).",
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
    tool = build_find_relatives_tool(args.graph or DEFAULT_GRAPH_PATH)
    preset = PRESETS[args.preset]
    node = args.node or preset["node"]
    relation_types = args.relation_types or preset["relation_types"]
    direction = args.direction or preset["direction"]
    depth = args.depth or preset["depth"]
    payload = {
        "nodes": [node],
        "relation_types": relation_types,
        "direction": direction,
        "depth": depth,
    }
    print(
        f"# 预设: {args.preset} -> {preset['description']} "
        f"(relation_types={relation_types}, direction={direction}, depth={depth})"
    )
    result = tool.invoke(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
