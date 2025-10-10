from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from structural_scaffolding.database import resolve_database_url

from .graph import build_workflow_graph
from .state import WorkflowAgentConfig, WorkflowAgentState


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute the workflow tracing pipeline.")
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Override the structural scaffolding database URL.",
    )
    parser.add_argument(
        "--root-path",
        type=str,
        default=None,
        help="Filter profiles by repository root path (optional).",
    )
    parser.add_argument(
        "--entry-points",
        type=Path,
        default=Path("results/entry_points.json"),
        help="Destination JSON file for detected entry points.",
    )
    parser.add_argument(
        "--call-graph",
        type=Path,
        default=Path("results/call_graph.json"),
        help="Destination JSON file for the call graph.",
    )
    parser.add_argument(
        "--workflows",
        type=Path,
        default=Path("results/workflow_scripts.json"),
        help="Destination JSON file for synthesised workflows.",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=Path("results/orchestration.json"),
        help="Optional JSON summary (from the orchestration agent) to thread into workflow synthesis.",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include test files when scanning for entry points.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=6,
        help="Maximum traversal depth when synthesising workflows.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="Maximum number of steps per synthesised workflow.",
    )
    parser.add_argument(
        "--synopsis-output",
        type=Path,
        default=Path("results/workflow_synopses.txt"),
        help="Write textual workflow synopses to this file (set to '-' to disable).",
    )
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    database_url = resolve_database_url(args.database_url)
    orchestration_summary = _load_orchestration_summary(args.summary_path)

    config = WorkflowAgentConfig(
        database_url=database_url,
        root_path=args.root_path,
        include_tests=args.include_tests,
        max_depth=args.max_depth,
        max_steps=args.max_steps,
        entry_points_path=args.entry_points,
        call_graph_path=args.call_graph,
        workflow_scripts_path=args.workflows,
        orchestration_summary=orchestration_summary,
    )

    graph = build_workflow_graph(config)

    print("Starting workflow tracing agent...", flush=True)
    initial_state: WorkflowAgentState = {
        "config": config,
        "events": [],
        "errors": [],
    }
    final_state = graph.invoke(initial_state)

    if final_state is None:
        print("Agent completed with no final state.", flush=True)
        return 1

    events = list(final_state.get("events", []))
    errors = list(final_state.get("errors", []))
    workflows = list(final_state.get("workflows", []))

    if events:
        print("=== Agent Events ===")
        for event in events:
            print(f"- {event}")

    if errors:
        print("=== Agent Errors ===")
        for error in errors:
            print(f"! {error}")

    print("=== Outputs ===")
    print(f"Entry points written to: {config.entry_points_path}")
    print(f"Call graph written to: {config.call_graph_path}")
    print(f"Workflow scripts written to: {config.workflow_scripts_path}")
    print(f"Synthesised workflows: {len(workflows)}")

    synopsis_output = args.synopsis_output
    if workflows and synopsis_output:
        if synopsis_output == Path("-"):
            synopsis_output = None
        if synopsis_output is not None:
            lines: list[str] = []
            for script in workflows:
                entry = getattr(script, "entry_point", None)
                entry_name = getattr(entry, "name", None) if entry else None
                if not entry_name and entry:
                    entry_name = getattr(entry, "profile_id", None)
                entry_label = entry_name or "<unknown entry>"
                lines.append(f"{entry_label}")
                synopsis = getattr(script, "synopsis", None)
                if isinstance(synopsis, str) and synopsis.strip():
                    lines.append(synopsis.strip())
                else:
                    lines.append("No synopsis available.")
                lines.append("")
            payload = "\n".join(lines).rstrip() + "\n"
            synopsis_output.parent.mkdir(parents=True, exist_ok=True)
            synopsis_output.write_text(payload)
            print(f"Workflow synopses written to: {synopsis_output}")

    print("Workflow tracing agent complete.", flush=True)

    return 0


def main() -> None:
    raise SystemExit(run())


def _load_orchestration_summary(summary_path: Path | None) -> str | None:
    if summary_path is None or not summary_path.exists():
        return None
    try:
        payload = json.loads(summary_path.read_text())
    except json.JSONDecodeError:
        return None

    if isinstance(payload, dict):
        text = payload.get("summary")
        if isinstance(text, str):
            return text.strip()
    if isinstance(payload, str):
        return payload.strip()
    return None


__all__ = ["main", "parse_args", "run"]


if __name__ == "__main__":
    main()
