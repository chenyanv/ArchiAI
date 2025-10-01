#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys


def _ensure_repo_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    repo_path = str(repo_root)
    if repo_path not in sys.path:
        sys.path.insert(0, repo_path)


_ensure_repo_on_path()

from structural_scaffolding.database import create_session
from structural_scaffolding.pipeline.context import build_l1_context
from structural_scaffolding.pipeline.data_access import load_profile
from structural_scaffolding.pipeline.prompts import build_l1_messages


def _format_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect the Level 1 prompt payload for a given profile.",
    )
    parser.add_argument("profile_id", help="Profile identifier to inspect")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional SQLAlchemy URL (defaults to STRUCTURAL_SCAFFOLD_DB_URL)",
    )
    args = parser.parse_args()

    session = create_session(args.database_url)
    try:
        record = load_profile(session, args.profile_id)
        if record is None:
            parser.error(f"Profile '{args.profile_id}' not found")

        context = build_l1_context(session, record)
    finally:
        session.close()

    messages = build_l1_messages(context)

    print("=== L1 Context ===")
    print(_format_json(asdict(context)))
    print()
    print("=== Chat Messages ===")
    for index, message in enumerate(messages, start=1):
        print(f"[{index}] role={message['role']}")
        print(message.get("content", ""))
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
