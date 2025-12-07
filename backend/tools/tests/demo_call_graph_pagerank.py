#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.call_graph_pagerank import (  # noqa: E402
    DEFAULT_GRAPH_PATH,
    build_call_graph_pagerank_tool,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview the output of the call graph PageRank tool.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of top nodes to display (default: 10).",
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
    tool = build_call_graph_pagerank_tool(args.graph or DEFAULT_GRAPH_PATH)
    result = tool.invoke({"limit": args.limit})
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
