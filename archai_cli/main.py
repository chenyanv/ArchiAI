"""ArchAI CLI entry point."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from orchestration_agent.graph import run_orchestration_agent

from .args import AnalyzeArgs, BrowseArgs, CommonArgs, parse_args
from .browser import (
    browse_component,
    load_plan,
    normalise_card_payload,
    select_component,
    write_plan,
)


def _load_or_run_orchestration(plan_path: Path, no_cache: bool) -> Dict[str, Any]:
    """Load cached plan or run orchestration agent."""
    plan = load_plan(plan_path)
    if plan and plan.get("component_cards") and not no_cache:
        print(f"✓ Loaded cached plan with {len(plan['component_cards'])} components")
        return plan

    print("Running orchestration agent..." if not plan else "Re-running orchestration...")
    plan = run_orchestration_agent()
    write_plan(plan, plan_path)
    print(f"✓ Generated plan with {len(plan.get('component_cards', []))} components")
    return plan


def _browse_with_plan(
    plan: Dict[str, Any],
    database_url: str | None,
    args: CommonArgs,
    log_tools: bool = True,
    show_tokens: bool = True,
) -> None:
    """Select and browse a component from the plan."""
    cards = [normalise_card_payload(c) for c in (plan.get("component_cards") or [])]
    card = select_component(cards, args.component_id)
    if card is None:
        print("No component selected. Bye!")
        return

    browse_component(
        card,
        database_url,
        debug_agent=args.debug_agent,
        log_llm=args.log_llm,
        log_tools=log_tools,
        no_cache=args.no_cache,
        show_tokens=show_tokens,
    )


def run_analyze(args: AnalyzeArgs) -> None:
    """Analyze a GitHub repository: download → index → orchestrate → browse."""
    from workspace import WorkspaceManager
    from workspace.github import GitHubError

    print(f"\n📦 Fetching repository from {args.github_url}...")
    try:
        workspace = WorkspaceManager().get_or_create(args.github_url, force_download=args.force_download)
    except GitHubError as e:
        print(f"❌ Error: {e}")
        return

    print(f"   → Workspace: {workspace.root}")

    if not workspace.is_indexed or args.force_download:
        print("\n🔍 Building structural index...")
        try:
            count = workspace.build_index()
            print(f"   ✓ Indexed {count} profiles")
        except Exception as e:
            print(f"❌ Indexing failed: {e}")
            return
    else:
        print("\n✓ Using cached index")

    os.environ["STRUCTURAL_SCAFFOLD_DB_URL"] = workspace.database_url
    os.environ["ARCHAI_GRAPH_PATH"] = str(workspace.call_graph_path)

    print("\n🤖 Running orchestration agent...")
    plan = _load_or_run_orchestration(workspace.plan_path, args.no_cache)
    _browse_with_plan(plan, workspace.database_url, args)


def run_browse(args: BrowseArgs) -> None:
    """Browse an existing orchestration plan."""
    plan = _load_or_run_orchestration(args.plan_path, args.no_cache)
    _browse_with_plan(plan, args.database_url, args, log_tools=args.log_tools, show_tokens=args.show_tokens)


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    if isinstance(args, AnalyzeArgs):
        run_analyze(args)
    else:
        run_browse(args)


if __name__ == "__main__":
    main()
