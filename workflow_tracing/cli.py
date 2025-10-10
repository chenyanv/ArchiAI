from __future__ import annotations

import argparse
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
        "--summary-path",
        type=Path,
        default=Path("results/orchestration.json"),
        help="Optional orchestration summary JSON file to seed the trace agent.",
    )
    parser.add_argument(
        "--trace-output",
        type=Path,
        default=Path("results/workflow_trace.md"),
        help="Destination file for the human-readable workflow narrative.",
    )
    parser.add_argument(
        "--trace-json",
        type=Path,
        default=Path("results/workflow_trace.json"),
        help="Destination file for the structured workflow narrative payload.",
    )
    parser.add_argument(
        "--max-directories",
        type=int,
        default=6,
        help="Maximum number of directories to inspect.",
    )
    parser.add_argument(
        "--profiles-per-directory",
        type=int,
        default=4,
        help="Maximum number of representative profiles to surface per directory.",
    )
    parser.add_argument(
        "--enable-llm-narrative",
        action="store_true",
        help="Use an LLM to rewrite the macro workflow narrative (falls back to deterministic text on failure).",
    )
    parser.add_argument(
        "--narrative-model",
        type=str,
        default=None,
        help="Override the model identifier when --enable-llm-narrative is set.",
    )
    parser.add_argument(
        "--narrative-system-prompt",
        type=str,
        default=None,
        help="Custom system prompt for LLM narrative synthesis.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress messages from the trace agent.",
    )
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    database_url = resolve_database_url(args.database_url)
    orchestration_summary = _load_orchestration_summary(args.summary_path)

    config = WorkflowAgentConfig(
        database_url=database_url,
        root_path=args.root_path,
        max_directories=args.max_directories,
        profiles_per_directory=args.profiles_per_directory,
        trace_output_path=args.trace_output,
        trace_json_path=args.trace_json,
        orchestration_summary=orchestration_summary,
        verbose=args.verbose,
        enable_llm_narrative=args.enable_llm_narrative,
        narrative_model=args.narrative_model,
        narrative_system_prompt=args.narrative_system_prompt,
    )

    graph = build_workflow_graph(config)

    if args.verbose:
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
    narrative = final_state.get("trace_narrative")

    if events:
        print("=== Agent Events ===")
        for event in events:
            print(f"- {event}")

    if errors:
        print("=== Agent Errors ===")
        for error in errors:
            print(f"! {error}")

    print("=== Outputs ===")
    if narrative is not None:
        stage_count = len(getattr(narrative, "stages", []) or [])
        print(f"Workflow narrative stages: {stage_count}")
    else:
        print("Workflow narrative stages: 0")
    print(f"Narrative written to: {config.trace_output_path}")
    print(f"Structured narrative written to: {config.trace_json_path}")

    if args.verbose:
        print("Workflow tracing agent complete.", flush=True)

    return 0


def main() -> None:
    raise SystemExit(run())


def _load_orchestration_summary(summary_path: Path | None) -> str | None:
    if summary_path is None or not summary_path.exists():
        return None
    try:
        payload = summary_path.read_text(encoding="utf-8")
    except OSError:
        return None

    import json

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        if payload.strip():
            return payload.strip()
        return None

    if isinstance(data, dict):
        text = data.get("summary")
        if isinstance(text, str):
            return text.strip()
    if isinstance(data, str):
        return data.strip()
    return None


__all__ = ["main", "parse_args", "run"]


if __name__ == "__main__":
    main()
