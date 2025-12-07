#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.get_call_graph_context import (  # noqa: E402
    DEFAULT_GRAPH_PATH,
    build_get_call_graph_context_tool,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Display inbound and outbound call context for a call graph node.",
    )
    parser.add_argument(
        "node_id",
        help="Call graph node identifier to inspect.",
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
    tool = build_get_call_graph_context_tool(args.graph or DEFAULT_GRAPH_PATH)
    payload = {"node_id": args.node_id}
    result = tool.invoke(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
