#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.get_neighbors import build_get_neighbors_tool  # noqa: E402
from tools.graph_queries import DEFAULT_GRAPH_PATH  # noqa: E402

DEFAULT_NODES: List[str] = [
    "python::agentic_reasoning/deep_research.py::DeepResearcher::_generate_reasoning",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview the Graph Grep get_neighbors output for ragflow-main nodes.",
    )
    parser.add_argument(
        "--nodes",
        nargs="+",
        default=DEFAULT_NODES,
        help="Node identifiers to inspect (defaults to a DeepResearcher helper).",
    )
    parser.add_argument(
        "--direction",
        choices=("in", "out", "all"),
        default="out",
        help="Traversal direction (default: out).",
    )
    parser.add_argument(
        "--edge-types",
        nargs="*",
        default=None,
        help="Optional list of edge types to include.",
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
    tool = build_get_neighbors_tool(args.graph or DEFAULT_GRAPH_PATH)
    payload = {
        "nodes": args.nodes,
        "direction": args.direction,
    }
    if args.edge_types:
        payload["edge_types"] = args.edge_types
    result = tool.invoke(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

