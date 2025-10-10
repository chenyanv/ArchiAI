from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from .models import ExplorationHistoryItem, PlannerOutput
from .state import TraceRegistry


def write_markdown(
    path: Path,
    planner_output: PlannerOutput,
    history: Sequence[ExplorationHistoryItem],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# Top-Down Workflow Trace", ""]
    lines.append("## Macro Narrative")
    lines.append("")
    lines.append(planner_output.summary.strip() or "_Planner did not return a summary._")
    lines.append("")

    if planner_output.notes:
        lines.append("## Notes")
        lines.append("")
        for note in planner_output.notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append("## Primary Components")
    lines.append("")
    if planner_output.components:
        for idx, component in enumerate(planner_output.components, start=1):
            lines.append(f"{idx}. **{component.name}** — {component.description}")
            if component.keywords:
                lines.append(f"   - Keywords: {', '.join(component.keywords)}")
            if component.trace_tokens:
                lines.append(f"   - Trace Tokens: {', '.join(component.trace_tokens)}")
            if component.evidence:
                lines.append(f"   - Evidence: {', '.join(component.evidence)}")
            lines.append("")
    else:
        lines.append("_No components were produced._")
        lines.append("")

    lines.append("## Exploration History")
    lines.append("")
    if not history:
        lines.append("_No interactive exploration captured._")
    else:
        for item in history:
            lines.append(f"### {item.timestamp.isoformat()} — Query: {item.exploration.query}")
            lines.append("")
            lines.append(item.exploration.analysis or "_No analysis returned._")
            lines.append("")
            if item.exploration.options:
                lines.append("Options:")
                for option in item.exploration.options:
                    lines.append(f"- **{option.title}**: {option.rationale or 'No rationale.'}")
                    lines.append(f"  - Workflow: {option.workflow or 'Not specified.'}")
                    if option.trace_tokens:
                        lines.append(f"  - Trace Tokens: {', '.join(option.trace_tokens)}")
                    if option.considerations:
                        lines.append(f"  - Considerations: {', '.join(option.considerations)}")
                lines.append("")
            if item.exploration.trace_seeds:
                lines.append("Trace Seeds:")
                for seed in item.exploration.trace_seeds:
                    label = seed.label or seed.token
                    lines.append(f"- `{seed.token}` ({seed.kind}) — {label}")
                    if seed.description:
                        lines.append(f"  - {seed.description}")
                lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_json(
    path: Path,
    planner_output: PlannerOutput,
    history: Sequence[ExplorationHistoryItem],
    registry: TraceRegistry,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "planner": planner_output.to_dict(),
        "history": [item.to_dict() for item in history],
        "trace_seeds": registry.snapshot(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = ["write_json", "write_markdown"]

