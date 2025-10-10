from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from structural_scaffolding.database import resolve_database_url
from workflow_tracing.cli import _load_orchestration_summary  # reuse helper

from .graph import build_top_down_graph
from .state import TopDownAgentConfig, TopDownAgentState, TraceRegistry


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive top-down workflow trace explorer.")
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Optional override for the structural scaffolding database URL.",
    )
    parser.add_argument(
        "--root-path",
        type=str,
        default=None,
        help="Scope traced profiles to a specific repository root (optional).",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=Path("results/orchestration.json"),
        help="Path to the orchestration summary JSON or text file.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("results/trace_top_down.md"),
        help="Markdown file to persist the top-down trace narrative.",
    )
    parser.add_argument(
        "--json-path",
        type=Path,
        default=Path("results/trace_top_down.json"),
        help="JSON file to persist the structured trace output.",
    )
    parser.add_argument(
        "--max-directories",
        type=int,
        default=8,
        help="Maximum number of directories to include in the initial context.",
    )
    parser.add_argument(
        "--profiles-per-directory",
        type=int,
        default=6,
        help="Representative profiles to keep per directory.",
    )
    parser.add_argument(
        "--component-limit",
        type=int,
        default=6,
        help="Maximum number of high-level components to request from the planner.",
    )
    parser.add_argument(
        "--no-planner-llm",
        action="store_true",
        help="Disable LLM-based macro planning (falls back to deterministic summaries).",
    )
    parser.add_argument(
        "--planner-model",
        type=str,
        default=None,
        help="Model identifier for the planner LLM (if enabled).",
    )
    parser.add_argument(
        "--planner-system-prompt",
        type=str,
        default=None,
        help="Custom system prompt for the planner LLM.",
    )
    parser.add_argument(
        "--no-analysis-llm",
        action="store_true",
        help="Disable LLM-based component analysis (falls back to deterministic context).",
    )
    parser.add_argument(
        "--analysis-model",
        type=str,
        default=None,
        help="Model identifier for the analyst LLM (if enabled).",
    )
    parser.add_argument(
        "--analysis-system-prompt",
        type=str,
        default=None,
        help="Custom system prompt for the analyst LLM.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print trace agent status updates.",
    )
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    database_url = resolve_database_url(args.database_url)
    orchestration_summary = _load_orchestration_summary(args.summary_path)

    config = TopDownAgentConfig(
        database_url=database_url,
        root_path=args.root_path,
        summary_path=args.summary_path,
        output_path=args.output_path,
        json_path=args.json_path,
        max_directories=args.max_directories,
        profiles_per_directory=args.profiles_per_directory,
        component_limit=args.component_limit,
        enable_planner_llm=not args.no_planner_llm,
        planner_model=args.planner_model,
        planner_system_prompt=args.planner_system_prompt,
        enable_analysis_llm=not args.no_analysis_llm,
        analysis_model=args.analysis_model,
        analysis_system_prompt=args.analysis_system_prompt,
        verbose=args.verbose,
    )

    graph = build_top_down_graph(config)

    if args.verbose:
        print("Launching top-down trace explorer...", flush=True)

    initial_state: TopDownAgentState = {
        "config": config,
        "events": [],
        "errors": [],
        "orchestration_summary": orchestration_summary,
        "trace_registry": TraceRegistry(),
    }

    final_state = graph.invoke(initial_state)
    if final_state is None:
        print("Top-down trace agent terminated without producing output.")
        return 1

    events = list(final_state.get("events", []))
    errors = list(final_state.get("errors", []))

    if events:
        print("=== Agent Events ===")
        for event in events:
            print(f"- {event}")
    if errors:
        print("=== Agent Errors ===")
        for error in errors:
            print(f"! {error}")

    if args.verbose:
        registry = final_state.get("trace_registry")
        if registry:
            print("Trace tokens registered: %d" % len(registry))
        print("Top-down trace explorer finished.", flush=True)

    return 0


def main() -> None:
    raise SystemExit(run())


__all__ = ["main", "parse_args", "run"]

