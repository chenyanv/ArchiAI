"""CLI argument parsing and dataclasses."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CommonArgs:
    """Arguments shared by all subcommands."""
    component_id: Optional[str] = None
    debug_agent: bool = False
    log_llm: bool = False
    no_cache: bool = False


@dataclass
class AnalyzeArgs(CommonArgs):
    """Arguments for the 'analyze' subcommand."""
    github_url: str = ""
    force_download: bool = False


@dataclass
class BrowseArgs(CommonArgs):
    """Arguments for the 'browse' subcommand."""
    workspace_id: str = ""
    plan_path: Path = field(default_factory=lambda: Path("results/orchestration_plan.json"))
    database_url: Optional[str] = None
    log_tools: bool = False
    show_tokens: bool = True


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--component-id", default=None, help="Auto-select this component.")
    parser.add_argument("--debug-agent", action="store_true", help="Print agent reasoning.")
    parser.add_argument("--log-llm", action="store_true", help="Print full LLM input context.")
    parser.add_argument("--no-cache", action="store_true", help="Disable response caching.")


def parse_args() -> AnalyzeArgs | BrowseArgs:
    """Parse CLI arguments and return typed args object."""
    parser = argparse.ArgumentParser(
        prog="archai",
        description="ArchAI: Analyze and explore codebases with AI agents.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # analyze subcommand
    analyze_parser = subparsers.add_parser("analyze", help="Analyze a GitHub repository")
    analyze_parser.add_argument("github_url", help="GitHub URL to analyze")
    analyze_parser.add_argument("--force-download", action="store_true", help="Re-download repo")
    _add_common_args(analyze_parser)

    # browse subcommand
    browse_parser = subparsers.add_parser("browse", help="Browse an existing orchestration plan")
    browse_parser.add_argument("workspace_id", help="Workspace identifier (e.g., owner-repo)")
    browse_parser.add_argument("--plan-path", default="results/orchestration_plan.json")
    browse_parser.add_argument("--database-url", default=None)
    browse_parser.add_argument("--log-tools", action="store_true", help="Print tool invocations.")
    _add_common_args(browse_parser)

    args = parser.parse_args()

    # Default command inference for backward compatibility
    if args.command is None:
        if len(sys.argv) > 1 and ("github.com" in sys.argv[1] or sys.argv[1].startswith("http")):
            args = parser.parse_args(["analyze"] + sys.argv[1:])
        else:
            args = parser.parse_args(["browse"] + sys.argv[1:])

    if args.command == "analyze":
        return AnalyzeArgs(
            github_url=args.github_url,
            component_id=args.component_id,
            debug_agent=args.debug_agent,
            log_llm=args.log_llm,
            no_cache=args.no_cache,
            force_download=args.force_download,
        )
    return BrowseArgs(
        workspace_id=args.workspace_id,
        plan_path=Path(args.plan_path).expanduser().resolve(),
        database_url=args.database_url,
        component_id=args.component_id,
        debug_agent=args.debug_agent,
        log_llm=args.log_llm,
        log_tools=getattr(args, "log_tools", False),
        no_cache=args.no_cache,
    )
