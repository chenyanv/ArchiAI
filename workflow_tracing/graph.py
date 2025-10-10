from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from langgraph.graph import StateGraph
from sqlalchemy.orm import Session

from structural_scaffolding.database import ProfileRecord, create_session

from .call_graph import CallGraphBuilder
from .entry_scanner import EntryPointScanner
from .models import CallGraphEdge, CallGraphNode, EntryPointCandidate, WorkflowScript
from .state import WorkflowAgentConfig, WorkflowAgentState, append_event
from .synthesizer import WorkflowSynthesizer


def build_workflow_graph(config: WorkflowAgentConfig) -> StateGraph:
    graph = StateGraph(WorkflowAgentState)

    @contextmanager
    def _session_scope() -> Session:
        session = create_session(config.database_url)
        try:
            yield session
        finally:
            session.close()

    def _decide_next_step(state: WorkflowAgentState) -> WorkflowAgentState:
        return state

    def _decide_route(state: WorkflowAgentState) -> str:
        if "entry_points" not in state:
            return "scan_entry_points"
        if "call_graph_edges" not in state:
            return "build_call_graph"
        if "workflows" not in state:
            return "synthesise_workflows"
        return "finish"

    def _scan_entry_points(state: WorkflowAgentState) -> WorkflowAgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        resolved_root_path = state.get("resolved_root_path", config.root_path)
        available_root_paths = list(state.get("available_root_paths", []))

        try:
            with _session_scope() as session:
                if not available_root_paths:
                    available_root_paths = sorted(
                        {row[0] for row in session.query(ProfileRecord.root_path).distinct()}
                    )

                resolution = _resolve_root_path(
                    requested=config.root_path,
                    current=resolved_root_path,
                    available=available_root_paths,
                )
                events.extend(resolution.events)
                errors.extend(resolution.errors)
                if resolution.resolved is None:
                    return {
                        "events": events,
                        "errors": errors,
                        "available_root_paths": available_root_paths,
                    }
                resolved_root_path = resolution.resolved

                scanner = EntryPointScanner(
                    session,
                    root_path=resolved_root_path,
                    include_tests=config.include_tests,
                )
                candidates: list[EntryPointCandidate] = scanner.scan()
                scanner.export(candidates, config.entry_points_path)
                diagnostics = scanner.diagnostics
        except Exception as exc:  # noqa: BLE001
            errors.append(f"entry_scan: {exc}")
            return {"errors": errors, "events": events}

        if diagnostics:
            events.append(
                "Entry scan stats: profiles=%d, signals=%d, detected_profiles=%d, candidates=%d "
                "(root_path=%r, include_tests=%s, skipped_test_path=%d, skipped_test_name=%d, skipped_missing_name=%d)"
                % (
                    diagnostics.profile_count,
                    diagnostics.signals_count,
                    diagnostics.detected_profiles,
                    diagnostics.candidate_count,
                    diagnostics.root_path,
                    diagnostics.include_tests,
                    diagnostics.skipped_test_path,
                    diagnostics.skipped_test_name,
                    diagnostics.skipped_missing_name,
                )
            )
            if diagnostics.sample_paths:
                sample = ", ".join(diagnostics.sample_paths)
                events.append(f"Entry scan sample paths: {sample}")

        events.append(f"Identified {len(candidates)} entry point candidates.")
        return {
            "entry_points": candidates,
            "events": events,
            "errors": errors,
            "resolved_root_path": resolved_root_path,
            "available_root_paths": available_root_paths,
        }

    def _build_call_graph(state: WorkflowAgentState) -> WorkflowAgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        resolved_root_path = state.get("resolved_root_path", config.root_path)

        try:
            with _session_scope() as session:
                builder = CallGraphBuilder(session, root_path=resolved_root_path)
                nodes, edges = builder.build()
                builder.export(nodes, edges, config.call_graph_path)
                diagnostics = builder.diagnostics
        except Exception as exc:  # noqa: BLE001
            errors.append(f"call_graph: {exc}")
            return {"errors": errors, "events": events}

        if diagnostics:
            events.append(
                "Call graph stats: profiles=%d, records_with_calls=%d, edges=%d (root_path=%r)"
                % (
                    diagnostics.profile_count,
                    diagnostics.records_with_calls,
                    diagnostics.edge_count,
                    resolved_root_path or diagnostics.root_path,
                )
            )
            if diagnostics.sample_callers:
                sample = ", ".join(diagnostics.sample_callers)
                events.append(f"Call graph sample caller files: {sample}")

        events.append(f"Constructed call graph with {len(nodes)} nodes and {len(edges)} edges.")
        return {
            "call_graph_nodes": nodes,
            "call_graph_edges": edges,
            "events": events,
            "errors": errors,
            "resolved_root_path": resolved_root_path,
        }

    def _synthesise_workflows(state: WorkflowAgentState) -> WorkflowAgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        entry_points: list[EntryPointCandidate] = state.get("entry_points", []) or []
        edges: list[CallGraphEdge] = state.get("call_graph_edges", []) or []

        try:
            with _session_scope() as session:
                synthesiser = WorkflowSynthesizer(
                    session,
                    orchestration_summary=config.orchestration_summary,
                    max_depth=config.max_depth,
                    max_steps=config.max_steps,
                )
                scripts: list[WorkflowScript] = synthesiser.synthesise(entry_points, edges)
                synthesiser.export(scripts, config.workflow_scripts_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"workflow_synthesis: {exc}")
            return {"errors": errors, "events": events}

        events.append(f"Synthesised {len(scripts)} workflow scripts.")
        return {
            "workflows": scripts,
            "events": events,
            "errors": errors,
        }

    def _finish(state: WorkflowAgentState) -> WorkflowAgentState:
        return append_event(state, "Workflow tracing complete.")

    graph.add_node("decide_next_step", _decide_next_step)
    graph.add_node("scan_entry_points", _scan_entry_points)
    graph.add_node("build_call_graph", _build_call_graph)
    graph.add_node("synthesise_workflows", _synthesise_workflows)
    graph.add_node("finish", _finish)

    graph.set_entry_point("decide_next_step")

    graph.add_conditional_edges(
        "decide_next_step",
        _decide_route,
        {
            "scan_entry_points": "scan_entry_points",
            "build_call_graph": "build_call_graph",
            "synthesise_workflows": "synthesise_workflows",
            "finish": "finish",
        },
    )

    graph.add_edge("scan_entry_points", "decide_next_step")
    graph.add_edge("build_call_graph", "decide_next_step")
    graph.add_edge("synthesise_workflows", "decide_next_step")

    graph.set_finish_point("finish")

    return graph.compile()


@dataclass(slots=True)
class _RootPathResolution:
    resolved: str | None
    events: list[str]
    errors: list[str]


def _resolve_root_path(
    *,
    requested: str | None,
    current: str | None,
    available: list[str],
) -> _RootPathResolution:
    events: list[str] = []
    errors: list[str] = []

    if not available:
        errors.append("No profiles found in the database. Ensure structural scaffolding has ingested profiles.")
        return _RootPathResolution(resolved=None, events=events, errors=errors)

    if requested and requested in available:
        return _RootPathResolution(resolved=requested, events=events, errors=errors)

    if current and current in available:
        return _RootPathResolution(resolved=current, events=events, errors=errors)

    if requested and requested not in available:
        if len(available) == 1:
            resolved = available[0]
            events.append(
                f"Requested root_path '{requested}' not found; using '{resolved}' (only available root path)."
            )
            return _RootPathResolution(resolved=resolved, events=events, errors=errors)
        errors.append(
            "Requested root_path '%s' not found. Available root paths: %s"
            % (requested, ", ".join(available))
        )
        return _RootPathResolution(resolved=None, events=events, errors=errors)

    if not requested:
        if len(available) == 1:
            resolved = available[0]
            events.append(f"No root_path provided; using '{resolved}' (only available root path).")
            return _RootPathResolution(resolved=resolved, events=events, errors=errors)

        errors.append(
            "Multiple root paths available (%s). Specify --root-path to select one."
            % ", ".join(available)
        )
        return _RootPathResolution(resolved=None, events=events, errors=errors)

    # Fallback should not normally be hit, but guard anyway.
    errors.append("Unable to resolve a root_path for workflow tracing.")
    return _RootPathResolution(resolved=None, events=events, errors=errors)


__all__ = ["build_workflow_graph"]
