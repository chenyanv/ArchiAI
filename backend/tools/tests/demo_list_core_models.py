#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.list_core_models import (  # noqa: E402
    DEFAULT_DIRECTORIES,
    DEFAULT_LIMIT,
    build_list_core_models_tool,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview the output of the list_core_models tool.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum number of models to display (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--directories",
        nargs="*",
        default=None,
        help=(
            "Optional path segments to filter model file paths. "
            f"Defaults to: {', '.join(DEFAULT_DIRECTORIES)}"
        ),
    )
    parser.add_argument(
        "--database-url",
        dest="database_url",
        type=str,
        default=None,
        help="Optional override for the structural scaffolding database URL.",
    )
    return parser.parse_args()


def _coerce_directories(raw: Optional[Sequence[str]]) -> Optional[List[str]]:
    if not raw:
        return None
    return [segment for segment in raw if segment]


def main() -> None:
    args = _parse_args()
    tool = build_list_core_models_tool()
    payload = {
        "limit": args.limit,
        "directories": _coerce_directories(args.directories),
        "database_url": args.database_url,
    }
    result = tool.invoke(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
