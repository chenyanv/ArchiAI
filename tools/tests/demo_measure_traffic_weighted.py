#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.evaluate_neighbors import (  # noqa: E402
    DEFAULT_GRAPH_PATH,
    DEFAULT_SCORING_METHOD,
    SUPPORTED_SCORING_METHODS,
    build_evaluate_neighbors_tool,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preview downstream neighbors for a call graph node, ranked by weighted traffic."
        ),
    )
    parser.add_argument(
        "node_id",
        help="Identifier of the node to inspect.",
    )
    parser.add_argument(
        "--graph",
        type=Path,
        default=None,
        help="Optional path to a call graph JSON export.",
    )
    parser.add_argument(
        "--scoring-method",
        default=DEFAULT_SCORING_METHOD,
        choices=sorted(SUPPORTED_SCORING_METHODS),
        help="Scoring strategy to apply when ranking neighbors.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for the number of results to display.",
    )
    return parser.parse_args()


def _render_results(results: List[Dict[str, Any]], limit: int | None = None) -> str:
    if limit is not None and limit >= 0:
        results = results[:limit]
    return json.dumps(results, indent=2, ensure_ascii=False)


def main() -> None:
    args = _parse_args()
    tool = build_evaluate_neighbors_tool(args.graph or DEFAULT_GRAPH_PATH)
    payload = {
        "node_id": args.node_id,
        "scoring_method": args.scoring_method,
    }
    results = tool.invoke(payload)
    print(_render_results(results, limit=args.limit))


if __name__ == "__main__":
    main()
