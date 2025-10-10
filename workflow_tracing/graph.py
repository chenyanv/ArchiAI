from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Sequence

from langgraph.graph import StateGraph

from workflow_tracing.hints import extract_directory_hints
from .models import DirectoryInsight, TraceNarrative
from .state import WorkflowAgentConfig, WorkflowAgentState, append_event
from .synthesizer import NarrativeSynthesisLLM, TraceNarrativeComposer
from .tools import DirectoryInsightTool, ProfileInsightTool


def build_workflow_graph(config: WorkflowAgentConfig) -> StateGraph:
    directory_tool = DirectoryInsightTool(max_directories=config.max_directories)
    profile_tool = ProfileInsightTool(max_profiles_per_directory=config.profiles_per_directory)
    narrative_llm = None
    if config.enable_llm_narrative:
        narrative_llm = NarrativeSynthesisLLM(
            model=config.narrative_model,
            system_prompt=config.narrative_system_prompt,
        )
    composer = TraceNarrativeComposer(narrative_llm=narrative_llm)

    graph = StateGraph(WorkflowAgentState)

    def initialise(state: WorkflowAgentState) -> WorkflowAgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        summary = config.orchestration_summary
        hints = extract_directory_hints(summary)

        if hints:
            events.append(
                "Extracted directory hints from orchestration summary: %s"
                % ", ".join(sorted(hints))
            )
        else:
            events.append("No directory hints detected; defaulting to top-level summaries.")

        return {
            "events": events,
            "errors": errors,
            "orchestration_summary": summary,
            "directory_hints": hints,
        }

    def collect_directories(state: WorkflowAgentState) -> WorkflowAgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        hints = list(state.get("directory_hints", []))

        try:
            directories = directory_tool(config, hints)
        except Exception as exc:  # noqa: BLE001 - bubble details to user
            errors.append(f"directory_insights: {exc}")
            return {"events": events, "errors": errors, "directory_insights": []}

        events.append(f"Collected {len(directories)} directory summaries.")
        return {
            "events": events,
            "errors": errors,
            "directory_insights": directories,
        }

    def collect_profiles(state: WorkflowAgentState) -> WorkflowAgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        directories = list(state.get("directory_insights", []))

        try:
            profiles = profile_tool(config, directories)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"profile_insights: {exc}")
            return {"events": events, "errors": errors, "profile_insights": []}

        events.append(f"Collected {len(profiles)} profile highlights.")
        return {
            "events": events,
            "errors": errors,
            "profile_insights": profiles,
        }

    def compose_narrative(state: WorkflowAgentState) -> WorkflowAgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        directories = list(state.get("directory_insights", []))
        profiles = list(state.get("profile_insights", []))
        orchestration_summary = state.get("orchestration_summary")

        project_name = _infer_project_name(config, directories, orchestration_summary)

        try:
            narrative = composer.compose(
                orchestration_summary=orchestration_summary,
                directories=directories,
                profiles=profiles,
                project_name=project_name,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"narrative: {exc}")
            return {"events": events, "errors": errors}

        events.append(
            "Composed workflow narrative with %d primary stages." % len(narrative.stages)
        )
        for note in getattr(narrative, "notes", []) or []:
            if note:
                events.append(f"Narrative note: {note}")
        return {
            "events": events,
            "errors": errors,
            "trace_narrative": narrative,
        }

    def write_outputs(state: WorkflowAgentState) -> WorkflowAgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        narrative: TraceNarrative | None = state.get("trace_narrative")

        if narrative is None:
            errors.append("output: no narrative generated")
            return {"events": events, "errors": errors}

        try:
            _write_text(config.trace_output_path, narrative.text)
            _write_json(config.trace_json_path, narrative)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"output: {exc}")
            return {"events": events, "errors": errors}

        events.append(
            "Wrote workflow narrative to %s and structured view to %s."
            % (config.trace_output_path, config.trace_json_path)
        )
        return {"events": events, "errors": errors}

    def finish(state: WorkflowAgentState) -> WorkflowAgentState:
        return append_event(state, "Workflow tracing complete.")

    graph.add_node("initialise", initialise)
    graph.add_node("collect_directories", collect_directories)
    graph.add_node("collect_profiles", collect_profiles)
    graph.add_node("compose_narrative", compose_narrative)
    graph.add_node("write_outputs", write_outputs)
    graph.add_node("finish", finish)

    graph.set_entry_point("initialise")
    graph.add_edge("initialise", "collect_directories")
    graph.add_edge("collect_directories", "collect_profiles")
    graph.add_edge("collect_profiles", "compose_narrative")
    graph.add_edge("compose_narrative", "write_outputs")
    graph.add_edge("write_outputs", "finish")
    graph.set_finish_point("finish")

    return graph.compile()


def _infer_project_name(
    config: WorkflowAgentConfig,
    directories: Sequence[DirectoryInsight],
    orchestration_summary: str | None,
) -> str:
    if config.root_path:
        candidate = Path(config.root_path).name
        if candidate:
            return candidate

    for directory in directories:
        candidate = Path(directory.root_path).name
        if candidate:
            return candidate

    if orchestration_summary:
        match = re.search(r"\b([A-Z][A-Za-z0-9]+)\b", orchestration_summary)
        if match:
            return match.group(1)

    return "Project"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, narrative: TraceNarrative) -> None:
    payload = narrative.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


__all__ = ["build_workflow_graph"]
