from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestration_agent import AgentConfig, run_orchestration_agent


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the LangGraph-based orchestration agent and emit a business logic summary.",
    )
    parser.add_argument(
        "--database-url",
        help="Override STRUCTURAL_SCAFFOLD_DB_URL when connecting to Postgres.",
    )
    parser.add_argument(
        "--root-path",
        help="Restrict directory summaries to a specific root path recorded in the database.",
    )
    parser.add_argument(
        "--max-directories",
        type=int,
        default=10,
        help="Maximum number of top-level directories to include in the analysis (default: 10).",
    )
    parser.add_argument(
        "--model",
        help="Override the provider model used during synthesis.",
    )
    parser.add_argument(
        "--no-row-counts",
        action="store_true",
        help="Skip collecting table row counts when inspecting the database schema.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose step-by-step progress logs.",
    )
    parser.add_argument(
        "--output",
        help="Optional file path to persist the orchestration result as JSON.",
    )
    return parser.parse_args(argv)


def _write_output(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    config = AgentConfig(
        database_url=args.database_url,
        root_path=args.root_path,
        max_directories=args.max_directories,
        include_row_counts=not args.no_row_counts,
        summary_model=args.model,
        verbose=not args.quiet,
    )

    result = run_orchestration_agent(config)
    summary_text = result.get("business_summary") or "No summary generated."
    events: List[str] = list(result.get("events", []))
    errors: List[str] = list(result.get("errors", []))

    print("=== Orchestration Agent Summary ===", flush=True)
    print(summary_text, flush=True)

    if events:
        print("\nEvents:", flush=True)
        for event in events:
            print(f"- {event}", flush=True)

    if errors:
        print("\nErrors:", flush=True)
        for error in errors:
            print(f"- {error}", flush=True)

    if args.output:
        payload = {
            "summary": summary_text,
            "events": events,
            "errors": errors,
        }
        _write_output(Path(args.output), payload)
        print(f"\nResult written to {args.output}", flush=True)

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
