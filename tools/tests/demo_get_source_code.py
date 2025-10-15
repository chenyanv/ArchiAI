#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.get_source_code import (  # noqa: E402
    build_get_source_code_tool,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview the source snippet returned by the get_source_code tool.",
    )
    parser.add_argument(
        "node_id",
        help="Structural profile identifier (e.g. python::api/db/services/llm_service.py::LLMBundle::chat).",
    )
    parser.add_argument(
        "--database-url",
        dest="database_url",
        type=str,
        default=None,
        help="Optional override for the structural scaffolding database URL.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    tool = build_get_source_code_tool()
    payload = {
        "node_id": args.node_id,
        "database_url": args.database_url,
    }
    result = tool.invoke(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
