#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.list_entry_points import (  # noqa: E402
    DEFAULT_GRAPH_PATH,
    build_list_entry_point_tool,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview the output of the list_entry_point tool.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of entry points to display (default: 20).",
    )
    parser.add_argument(
        "--framework",
        type=str,
        default=None,
        help="Optional framework filter (e.g. fastapi or flask).",
    )
    parser.add_argument(
        "--path-contains",
        dest="path_contains",
        type=str,
        default=None,
        help="Substring that must be present in the route path.",
    )
    parser.add_argument(
        "--docstring",
        action="store_true",
        help="Include docstring summaries in the output payload.",
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
    tool = build_list_entry_point_tool(args.graph or DEFAULT_GRAPH_PATH)
    payload = {
        "limit": args.limit,
        "framework": args.framework,
        "path_contains": args.path_contains,
        "include_docstring": args.docstring,
    }
    result = tool.invoke(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
