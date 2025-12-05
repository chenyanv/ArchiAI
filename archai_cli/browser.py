"""Component browser and drilldown navigation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from component_agent import (
    ComponentDrilldownRequest,
    NavigationBreadcrumb,
    NavigationNode,
    coerce_subagent_payload,
    run_component_agent,
)
from component_agent.token_tracker import TokenTracker

from .handlers import execute_action


# =============================================================================
# Logging
# =============================================================================

TOOL_DESCRIPTIONS = {
    "find_paths": "Finding execution paths",
    "get_source_code": "Reading source code",
    "get_call_graph_context": "Analyzing call graph",
    "get_neighbors": "Finding neighbors",
    "get_node_details": "Getting node details",
    "list_entry_point": "Listing entry points",
    "list_core_models": "Listing core models",
}


def _tool_usage_logger(tool_name: str, args: Dict[str, Any], result: Any) -> None:
    desc = TOOL_DESCRIPTIONS.get(tool_name, f"Using {tool_name}")
    print(f"\n🔧 Agent: {desc}...", flush=True)

    node_id = args.get("node_id", "")
    if node_id:
        symbol = node_id.split("::")[-1] if "::" in node_id else node_id
        print(f"   Target: {symbol}", flush=True)

    if isinstance(result, dict):
        if "paths" in result:
            print(f"   ✓ Found {len(result['paths'])} path(s)", flush=True)
        elif "code" in result:
            print(f"   ✓ Retrieved {len(result['code'].splitlines())} lines", flush=True)
        elif "callers" in result:
            print(f"   ✓ {len(result.get('callers', []))} callers, {len(result.get('callees', []))} callees", flush=True)
    elif isinstance(result, list):
        print(f"   ✓ Retrieved {len(result)} item(s)", flush=True)


def _llm_input_logger(messages: List[Dict[str, Any]]) -> None:
    print("\n=== LLM INPUT CONTEXT ===")
    try:
        print(json.dumps(messages, ensure_ascii=False, indent=2))
    except TypeError:
        print(repr(messages)[:4000])
    print("=== END LLM INPUT ===")


def _agent_logger(message: str) -> None:
    print(f"[agent] {message}")


# =============================================================================
# Plan I/O
# =============================================================================

def write_plan(plan: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)


def load_plan(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Unable to load plan from {path}: {exc}")
        return None


# =============================================================================
# Component Selection
# =============================================================================

def normalise_card_payload(card: Dict[str, Any]) -> Dict[str, Any]:
    payload = coerce_subagent_payload(card)
    if payload is not None:
        card["subagent_payload"] = payload
    elif not card.get("subagent_payload"):
        card.pop("subagent_payload", None)
    return card


def print_component_listing(cards: Sequence[Dict[str, Any]]) -> None:
    print("\n=== DISCOVERED COMPONENTS ===")
    for i, card in enumerate(cards, 1):
        cid = card.get("component_id", "<unknown>")
        module = card.get("module_name", "")
        conf = f" (confidence: {card['confidence']})" if card.get("confidence") else ""
        print(f"[{i}] {cid} :: {module}{conf}")
        if signal := card.get("business_signal"):
            print(f"    {signal}")
        for obj in (card.get("subagent_payload") or {}).get("objective") or []:
            print(f"      - {obj}")


def select_component(cards: Sequence[Dict[str, Any]], preset_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Interactively select a component from the list."""
    if not cards:
        print("No component cards produced.")
        return None

    if preset_id:
        for card in cards:
            if card.get("component_id") == preset_id:
                return card
        print(f"Component '{preset_id}' not found; falling back to interactive selection.")

    print_component_listing(cards)
    while True:
        choice = input("Select by number/id, or 'q' to quit: ").strip()
        if not choice:
            continue
        if choice.lower() in {"q", "quit", "exit"}:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(cards):
            return cards[int(choice) - 1]
        for card in cards:
            if card.get("component_id") == choice:
                return card
        print("Invalid selection.")


# =============================================================================
# Drilldown Navigation
# =============================================================================

def _render_component_overview(card: Dict[str, Any]) -> None:
    print("\n=== COMPONENT OVERVIEW ===")
    print(f"Component ID : {card.get('component_id')}")
    print(f"Module Name  : {card.get('module_name')}")
    print(f"Signal       : {card.get('business_signal')}")
    if entry_points := card.get("primary_entry_points"):
        print(f"Entry Points : {', '.join(e.get('route', '') for e in entry_points)}")
    for obj in (card.get("subagent_payload") or {}).get("objective") or []:
        print(f"  - {obj}")


def _print_next_layer(
    nodes: Sequence[NavigationNode],
    focus_label: str,
    focus_kind: str,
    rationale: str,
    agent_goal: str,
    breadcrumbs: Sequence[NavigationBreadcrumb],
    is_sequential: bool = False,
    workflow_narrative: Optional[str] = None,
) -> None:
    trail = " / ".join(c.title for c in breadcrumbs) or focus_label
    print(f"\n=== DRILLDOWN CONTEXT ===")
    print(f"Agent Goal : {agent_goal}")
    print(f"Focus      : {focus_label} ({focus_kind})")
    print(f"Rationale  : {rationale}")
    print(f"Breadcrumbs: {trail}")

    if is_sequential and workflow_narrative:
        print(f"\n📊 Workflow: {workflow_narrative}")
        sorted_nodes = sorted((n for n in nodes if n.sequence_order is not None), key=lambda n: n.sequence_order)
        for i, n in enumerate(sorted_nodes):
            print(f"   [{n.sequence_order + 1}] {n.title}")
            if i < len(sorted_nodes) - 1:
                print("      ↓")

    print("\nAvailable nodes:")
    for i, node in enumerate(nodes, 1):
        print(f"[{i}] {node.title} [{node.node_type}] -> {node.action.kind}")
        print(f"    {node.description}")
        for ev in node.evidence[:2]:
            label = ev.label or ev.node_id or ev.route or ev.file_path
            if label:
                print(f"    evidence: {ev.source_type} :: {label}")


def _prompt_node_choice(nodes: Sequence[NavigationNode]) -> Optional[int]:
    """Returns: node index, -1 for back, None for quit."""
    if not nodes:
        return None
    while True:
        choice = input("Pick node #, 'back', or 'q': ").strip().lower()
        if not choice:
            continue
        if choice in {"q", "quit", "exit"}:
            return None
        if choice in {"b", "back"}:
            return -1
        if choice.isdigit() and 1 <= int(choice) <= len(nodes):
            return int(choice) - 1
        print("Invalid selection.")


@dataclass
class CachedLayer:
    """Cached drilldown response."""
    nodes: List[NavigationNode]
    focus_label: str
    focus_kind: str
    rationale: str
    agent_goal: str
    is_sequential: bool = False
    workflow_narrative: Optional[str] = None


def browse_component(
    card: Dict[str, Any],
    database_url: Optional[str],
    *,
    debug_agent: bool,
    log_llm: bool,
    log_tools: bool,
    no_cache: bool = False,
    show_tokens: bool = False,
) -> None:
    """Interactive component exploration loop."""
    breadcrumbs: List[NavigationBreadcrumb] = []
    cache: Dict[str, CachedLayer] = {}
    token_tracker = TokenTracker() if show_tokens else None

    _render_component_overview(card)

    while True:
        cache_key = "/".join(c.node_key for c in breadcrumbs) or "__root__"

        if not no_cache and cache_key in cache:
            layer = cache[cache_key]
        else:
            if token_tracker:
                token_tracker.mark_checkpoint()

            response = run_component_agent(
                ComponentDrilldownRequest(
                    component_card=card,
                    breadcrumbs=breadcrumbs,
                    subagent_payload=coerce_subagent_payload(card),
                    database_url=database_url,
                ),
                debug=debug_agent,
                logger=_agent_logger if debug_agent else None,
                log_tool_usage=_tool_usage_logger if log_tools else None,
                log_llm_input=_llm_input_logger if log_llm else None,
                token_tracker=token_tracker,
            )

            if token_tracker:
                print(f"\n{token_tracker.summary()}")

            layer = CachedLayer(
                nodes=response.next_layer.nodes,
                focus_label=response.next_layer.focus_label,
                focus_kind=response.next_layer.focus_kind,
                rationale=response.next_layer.rationale,
                agent_goal=response.agent_goal,
                is_sequential=response.next_layer.is_sequential,
                workflow_narrative=response.next_layer.workflow_narrative,
            )
            cache[cache_key] = layer

        _print_next_layer(
            layer.nodes, layer.focus_label, layer.focus_kind,
            layer.rationale, layer.agent_goal, breadcrumbs,
            layer.is_sequential, layer.workflow_narrative,
        )

        while True:
            selection = _prompt_node_choice(layer.nodes)
            if selection is None:
                print("Exiting.")
                return
            if selection == -1:
                if breadcrumbs:
                    breadcrumbs.pop()
                    print("Moved up.")
                    break
                print("Already at root; exiting.")
                return

            node = layer.nodes[selection]
            if node.action.kind == "component_drilldown":
                breadcrumbs.append(NavigationBreadcrumb(
                    node_key=node.node_key,
                    title=node.title,
                    node_type=node.node_type,
                    target_id=node.action.target_id,
                    metadata=node.action.parameters,
                ))
                print(f"Deepening into {node.title}...")
                break
            execute_action(node, database_url)
