"""Convenience CLI for exercising the component drilldown agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from .graph import run_component_agent
from .schemas import ComponentDrilldownRequest, NavigationBreadcrumb, coerce_subagent_payload


def _load_component_card(plan_path: Path, component_id: str) -> Dict[str, Any]:
    with plan_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    cards: List[Dict[str, Any]] = payload.get("component_cards") or []
    for card in cards:
        if card.get("component_id") == component_id:
            return card
    raise SystemExit(f"Component '{component_id}' not found in {plan_path}.")


def _parse_breadcrumbs(raw: str | None) -> List[NavigationBreadcrumb]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid breadcrumbs JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise SystemExit("Breadcrumbs JSON must be a list of objects.")
    breadcrumbs: List[NavigationBreadcrumb] = []
    for item in payload:
        breadcrumbs.append(NavigationBreadcrumb.model_validate(item))
    return breadcrumbs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the component drilldown agent.")
    parser.add_argument(
        "component_id",
        help="Component identifier as emitted by the orchestration agent.",
    )
    parser.add_argument(
        "--plan-path",
        default="results/orchestration_plan.json",
        help="Path to the orchestration output containing component cards.",
    )
    parser.add_argument(
        "--breadcrumbs",
        default=None,
        help="Optional JSON array describing the drilldown path to resume.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional structural scaffolding database URL override.",
    )
    args = parser.parse_args()

    plan_path = Path(args.plan_path).expanduser().resolve()
    component_card = _load_component_card(plan_path, args.component_id)
    breadcrumbs = _parse_breadcrumbs(args.breadcrumbs)

    request = ComponentDrilldownRequest(
        component_card=component_card,
        breadcrumbs=breadcrumbs,
        subagent_payload=coerce_subagent_payload(component_card),
        database_url=args.database_url,
    )
    response = run_component_agent(request)
    print(response.model_dump_json(indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
