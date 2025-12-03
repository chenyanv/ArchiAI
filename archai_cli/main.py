"""Unified ArchAI CLI: orchestration → component selection → drilldown."""

from __future__ import annotations

import argparse
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
from component_agent.toolkit import DEFAULT_SUBAGENT_TOOLS
from orchestration_agent.graph import run_orchestration_agent
from tools import get_node_details_tool, get_source_code_tool


TOOL_REGISTRY = {tool.name: tool for tool in DEFAULT_SUBAGENT_TOOLS}


@dataclass
class CLIArgs:
    plan_path: Path
    database_url: Optional[str]
    component_id: Optional[str]
    debug_agent: bool
    log_llm: bool
    log_tools: bool


def _parse_args() -> CLIArgs:
    parser = argparse.ArgumentParser(
        description=(
            "Run the orchestration agent, pick a component, and drill down via the "
            "component sub-agent in one interactive session."
        )
    )
    parser.add_argument(
        "--plan-path",
        default="results/orchestration_plan.json",
        help="File path where the orchestration plan should be saved (default: results/orchestration_plan.json).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional structural scaffolding database URL override used by tools/sub-agent.",
    )
    parser.add_argument(
        "--component-id",
        default=None,
        help="Optional component_id to auto-select without prompting.",
    )
    parser.add_argument(
        "--debug-agent",
        action="store_true",
        help="Print agent reasoning and goals.",
    )
    parser.add_argument(
        "--log-llm",
        action="store_true",
        help="Print full LLM input context (verbose).",
    )
    parser.add_argument(
        "--log-tools",
        action="store_true",
        help="Print tool invocations and results.",
    )
    args = parser.parse_args()
    plan_path = Path(args.plan_path).expanduser().resolve()
    return CLIArgs(
        plan_path=plan_path,
        database_url=args.database_url,
        component_id=args.component_id,
        debug_agent=args.debug_agent,
        log_llm=args.log_llm,
        log_tools=args.log_tools,
    )


def _write_plan(plan: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2)


def _load_plan(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Unable to load cached orchestration plan from {path}: {exc}")
        return None
    if not isinstance(data, dict):
        print(f"Cached plan at {path} is not a JSON object; ignoring it.")
        return None
    return data


def _serialise_for_log(value: Any, limit: int = 600) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=False)
    except TypeError:
        rendered = repr(value)
    if len(rendered) <= limit:
        return rendered
    return rendered[:limit] + "…"


def _tool_usage_logger(tool_name: str, args: Dict[str, Any], result: Any) -> None:
    print("\n=== AGENT TOOL INVOCATION ===")
    print(f"Tool   : {tool_name}")
    print(f"Args   : {_serialise_for_log(args)}")
    print(f"Result : {_serialise_for_log(result)}")
    print("=== END TOOL INVOCATION ===")


def _llm_input_logger(messages: List[Dict[str, Any]]) -> None:
    try:
        rendered = json.dumps(messages, ensure_ascii=False, indent=2)
    except TypeError:
        rendered = _serialise_for_log(messages, limit=4000)
    print("\n=== LLM INPUT CONTEXT ===")
    print(rendered)
    print("=== END LLM INPUT ===")


def _normalise_card_payload(card: Dict[str, Any]) -> Dict[str, Any]:
    payload = coerce_subagent_payload(card)
    if payload is not None:
        card["subagent_payload"] = payload
    elif not card.get("subagent_payload"):
        card.pop("subagent_payload", None)
    return card


def _print_component_listing(cards: Sequence[Dict[str, Any]]) -> None:
    print("\n=== DISCOVERED COMPONENTS ===")
    for index, card in enumerate(cards, start=1):
        component_id = card.get("component_id", "<unknown>")
        module_name = card.get("module_name", "")
        signal = card.get("business_signal", "")
        confidence = card.get("confidence")
        confidence_str = f" (confidence: {confidence})" if confidence else ""
        print(f"[{index}] {component_id} :: {module_name}{confidence_str}")
        if signal:
            print(f"    {signal}")
        objectives = (card.get("subagent_payload") or {}).get("objective") or []
        if objectives:
            print("    Objectives:")
            for objective in objectives:
                print(f"      - {objective}")


def _select_component(cards: Sequence[Dict[str, Any]], preset_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not cards:
        print("No component cards produced by orchestration agent.")
        return None
    if preset_id:
        for card in cards:
            if card.get("component_id") == preset_id:
                return card
        print(f"Component '{preset_id}' not found; falling back to interactive selection.")
    _print_component_listing(cards)
    while True:
        choice = input("Select a component by number, type a component_id, or 'q' to quit: ").strip()
        if not choice:
            continue
        if choice.lower() in {"q", "quit", "exit"}:
            return None
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(cards):
                return cards[index - 1]
        for card in cards:
            if card.get("component_id") == choice:
                return card
        print("Invalid selection. Try again.")


def _render_component_overview(card: Dict[str, Any]) -> None:
    print("\n=== COMPONENT OVERVIEW ===")
    print(f"Component ID : {card.get('component_id')}")
    print(f"Module Name  : {card.get('module_name')}")
    print(f"Signal       : {card.get('business_signal')}")
    entry_points = card.get("primary_entry_points") or []
    if entry_points:
        routes = ", ".join(entry.get("route", "") for entry in entry_points)
        print(f"Entry Points : {routes}")
    objectives = (card.get("subagent_payload") or {}).get("objective") or []
    if objectives:
        print("Objectives   :")
        for objective in objectives:
            print(f"  - {objective}")


def _print_next_layer(nodes: Sequence[NavigationNode], focus_label: str, focus_kind: str, rationale: str, agent_goal: str, breadcrumbs: Sequence[NavigationBreadcrumb]) -> None:
    trail = " / ".join(crumb.title for crumb in breadcrumbs) or focus_label
    print("\n=== DRILLDOWN CONTEXT ===")
    print(f"Agent Goal : {agent_goal}")
    print(f"Focus      : {focus_label} ({focus_kind})")
    print(f"Rationale  : {rationale}")
    print(f"Breadcrumbs: {trail}")
    print("\nAvailable nodes:")
    for index, node in enumerate(nodes, start=1):
        print(
            f"[{index}] {node.title} [{node.node_type}] -> action={node.action.kind}, key={node.node_key}"
        )
        print(f"    {node.description}")
        highlights = node.evidence[:2]
        for evidence in highlights:
            label = evidence.label or evidence.node_id or evidence.route or evidence.file_path
            if label:
                print(f"    evidence: {evidence.source_type} :: {label}")


def _prompt_node_choice(nodes: Sequence[NavigationNode]) -> Optional[int]:
    if not nodes:
        return None
    while True:
        choice = input("Pick a node by number, 'back' to go up, or 'q' to exit: ").strip().lower()
        if not choice:
            continue
        if choice in {"q", "quit", "exit"}:
            return None
        if choice in {"b", "back"}:
            return -1
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(nodes):
                return index - 1
        print("Invalid selection. Try again.")


def _ensure_database_arg(payload: Dict[str, Any], database_url: Optional[str]) -> Dict[str, Any]:
    if not database_url:
        return payload
    if "database_url" not in payload:
        payload = dict(payload)
        payload["database_url"] = database_url
    return payload


def _handle_inspect_source(target_id: Optional[str], database_url: Optional[str]) -> None:
    if not target_id:
        print("No node_id provided for inspect_source action.")
        return
    try:
        payload = _ensure_database_arg({"node_id": target_id}, database_url)
        result = get_source_code_tool.invoke(payload)
    except Exception as exc:  # pragma: no cover - interactive feedback
        print(f"[ERROR] Unable to fetch source: {exc}")
        return
    print("\n=== SOURCE SNIPPET ===")
    file_path = result.get("file_path", "")
    start_line = result.get("start_line")
    end_line = result.get("end_line")
    header = f"{file_path}:{start_line}-{end_line}" if file_path else "Snippet"
    print(header)
    print(result.get("code", "<no code>"))
    print("=== END SOURCE ===")


def _handle_inspect_node(target_id: Optional[str], database_url: Optional[str]) -> None:
    if not target_id:
        print("No node_id provided for inspect_node action.")
        return
    try:
        payload = _ensure_database_arg({"node_id": target_id}, database_url)
        result = get_node_details_tool.invoke(payload)
    except Exception as exc:
        print(f"[ERROR] Unable to fetch node details: {exc}")
        return
    print("\n=== NODE DETAILS ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _handle_inspect_tool(parameters: Dict[str, Any], database_url: Optional[str]) -> None:
    tool_name = parameters.get("tool_name")
    if not tool_name:
        print("inspect_tool action missing 'tool_name'.")
        return
    tool = TOOL_REGISTRY.get(tool_name)
    if not tool:
        print(f"Tool '{tool_name}' is not registered.")
        return
    tool_args = dict(parameters.get("tool_args") or {})
    schema = getattr(tool, "args_schema", None)
    if database_url and schema is not None:
        model_fields = getattr(schema, "model_fields", {})
        if "database_url" in model_fields and "database_url" not in tool_args:
            tool_args["database_url"] = database_url
    try:
        result = tool.invoke(tool_args)
    except Exception as exc:
        print(f"[ERROR] Tool invocation failed: {exc}")
        return
    print(f"\n=== TOOL RESULT ({tool_name}) ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _handle_graph_overlay(parameters: Dict[str, Any]) -> None:
    print("\n=== GRAPH OVERLAY REQUEST ===")
    print(json.dumps(parameters or {}, ensure_ascii=False, indent=2))
    print("(Render this payload in the frontend graph viewer.)")


def _execute_action(node: NavigationNode, database_url: Optional[str]) -> Optional[str]:
    kind = node.action.kind
    if kind == "inspect_source":
        _handle_inspect_source(node.action.target_id, database_url)
    elif kind == "inspect_node":
        _handle_inspect_node(node.action.target_id, database_url)
    elif kind == "inspect_tool":
        _handle_inspect_tool(node.action.parameters, database_url)
    elif kind == "graph_overlay":
        _handle_graph_overlay(node.action.parameters)
    else:
        print(f"Unknown action kind '{kind}'.")
    return kind


def _build_breadcrumb(node: NavigationNode) -> NavigationBreadcrumb:
    return NavigationBreadcrumb(
        node_key=node.node_key,
        title=node.title,
        node_type=node.node_type,
        target_id=node.action.target_id,
        metadata=node.action.parameters,
    )


def _agent_logger(message: str) -> None:
    print(f"[agent] {message}")


def _browse_component(
    card: Dict[str, Any],
    database_url: Optional[str],
    *,
    debug_agent: bool,
    log_llm: bool,
    log_tools: bool
) -> None:
    breadcrumbs: List[NavigationBreadcrumb] = []
    _render_component_overview(card)
    while True:
        request = ComponentDrilldownRequest(
            component_card=card,
            breadcrumbs=breadcrumbs,
            subagent_payload=coerce_subagent_payload(card),
            database_url=database_url,
        )
        response = run_component_agent(
            request,
            debug=debug_agent,
            logger=_agent_logger if debug_agent else None,
            log_tool_usage=_tool_usage_logger if log_tools else None,
            log_llm_input=_llm_input_logger if log_llm else None,
        )
        nodes = response.next_layer.nodes
        _print_next_layer(
            nodes,
            response.next_layer.focus_label,
            response.next_layer.focus_kind,
            response.next_layer.rationale,
            response.agent_goal,
            response.breadcrumbs or breadcrumbs,
        )
        while True:
            selection = _prompt_node_choice(nodes)
            if selection is None:
                print("Exiting component exploration.")
                return
            if selection == -1:
                if breadcrumbs:
                    breadcrumbs.pop()
                    print("Moved up one level.")
                    break
                print("Already at root; exiting component exploration.")
                return
            node = nodes[selection]
            if node.action.kind == "component_drilldown":
                breadcrumbs.append(_build_breadcrumb(node))
                print(f"Deepening into {node.title}...")
                break
            _execute_action(node, database_url)
        # Loop continues to refresh drilldown view


def main() -> None:
    args = _parse_args()
    plan = _load_plan(args.plan_path)
    if plan and plan.get("component_cards"):
        print(f"Loaded cached orchestration plan from {args.plan_path}.")
    else:
        if plan:
            print(
                f"Cached plan at {args.plan_path} has no component cards; re-running orchestration agent..."
            )
        else:
            print("No cached orchestration plan found; running orchestration agent...")
        plan = run_orchestration_agent()
        _write_plan(plan, args.plan_path)
    cards = [_normalise_card_payload(card) for card in (plan.get("component_cards") or [])]
    component_card = _select_component(cards, args.component_id)
    if component_card is None:
        print("No component selected. Bye!")
        return
    _browse_component(
        component_card,
        args.database_url,
        debug_agent=args.debug_agent,
        log_llm=args.log_llm,
        log_tools=args.log_tools,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
