from __future__ import annotations

import logging
from typing import Optional

from langgraph.graph import StateGraph

from .state import AgentConfig, AgentState
from .tools import BusinessLogicSynthesizer, DirectorySummaryTool, TableInspectorTool

logger = logging.getLogger(__name__)


def build_orchestration_graph(
    config: AgentConfig,
    *,
    directory_summary_tool: Optional[DirectorySummaryTool] = None,
    table_inspector_tool: Optional[TableInspectorTool] = None,
    synthesizer: Optional[BusinessLogicSynthesizer] = None,
):
    """Construct a LangGraph workflow that orchestrates architecture discovery."""

    directory_summary_tool = directory_summary_tool or DirectorySummaryTool(
        max_directories=config.max_directories
    )
    table_inspector_tool = table_inspector_tool or TableInspectorTool(
        include_row_counts=config.include_row_counts
    )
    synthesizer = synthesizer or BusinessLogicSynthesizer(model=config.summary_model)

    graph = StateGraph(AgentState)

    def _emit(message: str) -> None:
        if config.verbose:
            print(f"[OrchestrationAgent] {message}")

    def collect_directory_summaries(state: AgentState) -> AgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        _emit("Collecting top-level directory summaries...")
        try:
            results = directory_summary_tool(config)
            events.append(f"Collected {len(results)} directory summaries.")
            _emit(f"Collected {len(results)} directory summaries.")
            return {"directory_summaries": results, "events": events, "errors": errors}
        except Exception as exc:  # noqa: BLE001 - propagate context to end user
            logger.exception("Failed to collect directory summaries")
            errors.append(f"directory_summaries: {exc}")
            _emit(f"Directory summary collection failed: {exc}")
            return {"directory_summaries": [], "events": events, "errors": errors}

    def inspect_tables(state: AgentState) -> AgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        _emit("Inspecting database tables...")
        try:
            snapshots = table_inspector_tool(config)
            events.append(f"Inspected {len(snapshots)} database tables.")
            _emit(f"Inspected {len(snapshots)} database tables.")
            return {"table_snapshots": snapshots, "events": events, "errors": errors}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to inspect tables")
            errors.append(f"table_inspection: {exc}")
            _emit(f"Table inspection failed: {exc}")
            return {"table_snapshots": [], "events": events, "errors": errors}

    def synthesize_summary(state: AgentState) -> AgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        directory_summaries = list(state.get("directory_summaries", []))
        table_snapshots = list(state.get("table_snapshots", []))
        _emit("Synthesising business logic narrative...")
        try:
            summary = synthesizer(directory_summaries, table_snapshots)
            events.append("Synthesised business logic narrative.")
            _emit("Synthesis complete.")
            return {
                "business_summary": summary,
                "events": events,
                "errors": errors,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to synthesise business summary")
            errors.append(f"synthesis: {exc}")
            _emit(f"Synthesis failed: {exc}")
            return {
                "business_summary": "",
                "events": events,
                "errors": errors,
            }

    graph.add_node("collect_directory_summaries", collect_directory_summaries)
    graph.add_node("inspect_tables", inspect_tables)
    graph.add_node("synthesize_summary", synthesize_summary)

    graph.set_entry_point("collect_directory_summaries")
    graph.add_edge("collect_directory_summaries", "inspect_tables")
    graph.add_edge("inspect_tables", "synthesize_summary")
    graph.set_finish_point("synthesize_summary")

    return graph.compile()
