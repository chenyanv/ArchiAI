from __future__ import annotations

from typing import List, Sequence

from langgraph.graph import StateGraph

from workflow_tracing.graph import _infer_project_name  # reuse naming heuristic
from workflow_tracing.hints import extract_directory_hints
from workflow_tracing.models import DirectoryInsight, ProfileInsight

from .models import ComponentExploration, ExplorationHistoryItem, TraceSeed, now_utc
from .state import (
    TopDownAgentConfig,
    TopDownAgentState,
    TraceRegistry,
    append_event,
)
from .synthesizer import ComponentAnalyst, TopLevelPlanner
from .tools import (
    RepositoryContextLoader,
    build_directory_seeds,
    build_profile_seeds,
    match_directories,
    match_profiles,
)
from .writer import write_json, write_markdown


def build_top_down_graph(config: TopDownAgentConfig) -> StateGraph:
    loader = RepositoryContextLoader(config)
    planner = TopLevelPlanner(
        component_limit=config.component_limit,
        enable_llm=config.enable_planner_llm,
        model=config.planner_model,
        system_prompt=config.planner_system_prompt,
    )
    analyst = ComponentAnalyst(
        enable_llm=config.enable_analysis_llm,
        model=config.analysis_model,
        system_prompt=config.analysis_system_prompt,
    )

    graph = StateGraph(TopDownAgentState)
    config_ref = config

    def initialise(state: TopDownAgentState) -> TopDownAgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        summary = state.get("orchestration_summary")
        hints = extract_directory_hints(summary)
        registry = state.get("trace_registry") or TraceRegistry()

        if hints:
            events.append("Derived directory hints from orchestration summary: %s" % ", ".join(hints))
        else:
            events.append("No directory hints detected; exploring top-level directories.")

        return {
            "events": events,
            "errors": errors,
            "directory_hints": hints,
            "trace_registry": registry,
        }

    def collect_context(state: TopDownAgentState) -> TopDownAgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        hints = list(state.get("directory_hints", []))
        registry: TraceRegistry = state.get("trace_registry") or TraceRegistry()

        try:
            directories, profiles = loader.load(config, hints)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"context: {exc}")
            return {"events": events, "errors": errors, "directory_insights": [], "profile_insights": []}

        registry.extend(build_directory_seeds(directories))
        registry.extend(build_profile_seeds(profiles))

        events.append(
            "Loaded %d directories and %d representative profiles."
            % (len(directories), len(profiles))
        )

        return {
            "events": events,
            "errors": errors,
            "directory_insights": directories,
            "profile_insights": profiles,
            "trace_registry": registry,
        }

    def plan_top_level(state: TopDownAgentState) -> TopDownAgentState:
        events = list(state.get("events", []))
        errors = list(state.get("errors", []))
        summary = state.get("orchestration_summary")
        directories = list(state.get("directory_insights", []))
        profiles = list(state.get("profile_insights", []))
        registry: TraceRegistry = state.get("trace_registry") or TraceRegistry()

        planner_output = planner(summary, directories, profiles, registry.all())
        events.append("Synthesised macro summary with %d components." % len(planner_output.components))

        component_seeds = _build_component_seeds(planner_output)
        registry.extend(component_seeds)

        return {
            "events": events,
            "errors": errors,
            "planner_output": planner_output,
            "trace_registry": registry,
        }

    def interactive_loop(state: TopDownAgentState) -> TopDownAgentState:
        config = state.get("config", config_ref)
        planner_output = state.get("planner_output")
        directories = list(state.get("directory_insights", []))
        profiles = list(state.get("profile_insights", []))
        registry: TraceRegistry = state.get("trace_registry") or TraceRegistry()
        history = list(state.get("history", []))

        if planner_output is None:
            print("Planner output missing; aborting interactive exploration.")
            return state

        if not config.interactive_enabled:
            _display_initial_summary(planner_output, config, directories)
            print(
                "Interactive input disabled (stdin is not a TTY). Skipping interactive loop.",
                flush=True,
            )
            events = list(state.get("events", []))
            events.append("Interactive loop skipped (stdin not a TTY).")
            return {
                "events": events,
                "errors": list(state.get("errors", [])),
                "trace_registry": registry,
                "history": history,
                "planner_output": planner_output,
            }

        _display_initial_summary(planner_output, config, directories)

        while True:
            try:
                user_input = input("> ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nExiting trace explorer.")
                break

            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit", "q"}:
                print("Trace exploration ended by user.")
                break
            if user_input.lower() in {"help", "?"}:
                _display_help()
                continue
            if user_input.lower() == "list":
                _display_trace_tokens(registry)
                continue

            exploration = _run_component_analysis(
                user_input,
                analyst,
                directories,
                profiles,
                registry,
            )
            history.append(ExplorationHistoryItem(timestamp=now_utc(), exploration=exploration))
            _display_exploration(exploration)

            # Extend registry with any new seeds surfaced by the exploration.
            for seed in exploration.trace_seeds:
                registry.add(seed)

        events = list(state.get("events", []))
        events.append("Interactive exploration complete with %d queries." % len(history))
        return {
            "events": events,
            "errors": list(state.get("errors", [])),
            "trace_registry": registry,
            "history": history,
            "planner_output": planner_output,
        }

    def write_outputs_node(state: TopDownAgentState) -> TopDownAgentState:
        planner_output = state.get("planner_output")
        if planner_output is None:
            return append_event(state, "Skipped writing outputs; planner output unavailable.")

        history = list(state.get("history", []))
        registry: TraceRegistry = state.get("trace_registry") or TraceRegistry()

        try:
            write_markdown(config.output_path, planner_output, history)
            write_json(config.json_path, planner_output, history, registry)
        except Exception as exc:  # noqa: BLE001
            return {
                "events": list(state.get("events", [])),
                "errors": list(state.get("errors", [])) + [f"output: {exc}"],
                "planner_output": planner_output,
                "history": history,
                "trace_registry": registry,
            }

        events = list(state.get("events", []))
        events.append(
            "Persisted top-down trace to %s and %s."
            % (config.output_path, config.json_path)
        )
        return {
            "events": events,
            "errors": list(state.get("errors", [])),
            "planner_output": planner_output,
            "history": history,
            "trace_registry": registry,
        }

    def finish(state: TopDownAgentState) -> TopDownAgentState:
        return append_event(state, "Top-down trace workflow complete.")

    graph.add_node("initialise", initialise)
    graph.add_node("collect_context", collect_context)
    graph.add_node("plan_top_level", plan_top_level)
    graph.add_node("interactive_loop", interactive_loop)
    graph.add_node("write_outputs", write_outputs_node)
    graph.add_node("finish", finish)

    graph.set_entry_point("initialise")
    graph.add_edge("initialise", "collect_context")
    graph.add_edge("collect_context", "plan_top_level")
    graph.add_edge("plan_top_level", "interactive_loop")
    graph.add_edge("interactive_loop", "write_outputs")
    graph.add_edge("write_outputs", "finish")
    graph.set_finish_point("finish")

    return graph.compile()


def _display_initial_summary(
    planner_output,
    config: TopDownAgentConfig,
    directories: Sequence[DirectoryInsight],
) -> None:
    print("", flush=True)
    print("=== Macro Workflow Summary ===", flush=True)
    print(planner_output.summary, flush=True)
    if planner_output.notes:
        print("", flush=True)
        print("Notes:", flush=True)
        for note in planner_output.notes:
            print(f"- {note}", flush=True)
    print("", flush=True)
    print("Primary Components (trace using numbers, keywords, or listed trace tokens):", flush=True)
    for idx, component in enumerate(planner_output.components, start=1):
        keywords = ", ".join(component.keywords) if component.keywords else "No keywords provided."
        tokens = ", ".join(component.trace_tokens) if component.trace_tokens else "No trace tokens yet."
        print(f"{idx}. {component.name}", flush=True)
        print(f"   Description: {component.description}", flush=True)
        print(f"   Keywords: {keywords}", flush=True)
        print(f"   Trace Tokens: {tokens}", flush=True)
        if component.evidence:
            print(f"   Evidence: {', '.join(component.evidence)}", flush=True)
    print("", flush=True)
    project_name = _infer_project_name(config, directories, planner_output.summary)
    print(
        "Enter a component keyword, file path, trace token, or type 'list' to see available tokens. "
        "Type 'exit' when finished.",
        flush=True,
    )
    print(f"(Project context inferred as: {project_name})", flush=True)


def _display_help() -> None:
    print(
        "Commands:\n"
        "  - Enter any keyword (e.g., 'document parser') to see existing implementations.\n"
        "  - Enter a trace token (directory path, profile ID, component alias) to drill down directly.\n"
        "  - 'list' shows known trace tokens.\n"
        "  - 'exit' ends the session.",
        flush=True,
    )


def _display_trace_tokens(registry: TraceRegistry) -> None:
    seeds = registry.all()
    if not seeds:
        print("No trace tokens registered yet.", flush=True)
        return
    print("Trace tokens that you can use directly:", flush=True)
    for seed in seeds:
        print(f"- {seed.token} ({seed.kind}) — {seed.label}", flush=True)


def _run_component_analysis(
    query: str,
    analyst: ComponentAnalyst,
    directories: Sequence[DirectoryInsight],
    profiles: Sequence[ProfileInsight],
    registry: TraceRegistry,
) -> ComponentExploration:
    matched_seeds = registry.search(query)

    component_related: List[TraceSeed] = []
    for seed in matched_seeds:
        if seed.kind != "component":
            continue
        trace_tokens = seed.metadata.get("trace_tokens", "") if seed.metadata else ""
        for token in trace_tokens.split(","):
            candidate = registry.get(token.strip())
            if candidate and candidate not in component_related:
                component_related.append(candidate)

    matched_seeds.extend(component_related)

    seed_directories = _seeds_to_directories(matched_seeds, directories)
    seed_profiles = _seeds_to_profiles(matched_seeds, profiles)

    keyword_directories = match_directories(query, directories)
    keyword_profiles = match_profiles(query, profiles)

    combined_directories = _dedupe_directories(seed_directories + keyword_directories)
    combined_profiles = _dedupe_profiles(seed_profiles + keyword_profiles)

    directory_context_seeds = build_directory_seeds(combined_directories)
    profile_context_seeds = build_profile_seeds(combined_profiles)
    active_seeds = _dedupe_seeds(matched_seeds + directory_context_seeds + profile_context_seeds)
    source_tokens = list(dict.fromkeys(registry.tokens() + [seed.token for seed in active_seeds]))[:25]

    exploration = analyst.explore(
        query,
        directories=combined_directories,
        profiles=combined_profiles,
        active_seeds=active_seeds,
        source_tokens=source_tokens,
    )
    return exploration


def _display_exploration(exploration) -> None:
    print("", flush=True)
    print(f"=== {exploration.query} ===", flush=True)
    print(exploration.analysis or "No analysis returned.", flush=True)
    if exploration.options:
        print("", flush=True)
        print("Options:", flush=True)
        for option in exploration.options:
            print(f"- {option.title}", flush=True)
            if option.rationale:
                print(f"  Rationale: {option.rationale}", flush=True)
            print(f"  Workflow: {option.workflow}", flush=True)
            if option.trace_tokens:
                print(f"  Trace Tokens: {', '.join(option.trace_tokens)}", flush=True)
            if option.considerations:
                print(f"  Considerations: {', '.join(option.considerations)}", flush=True)
    if exploration.trace_seeds:
        print("", flush=True)
        print("Trace seeds you can reuse next:", flush=True)
        for seed in exploration.trace_seeds:
            summary = seed.description or seed.summary or ""
            summary = summary[:180] + "..." if summary and len(summary) > 180 else summary
            print(f"- {seed.token} ({seed.kind}) — {seed.label}", flush=True)
            if summary:
                print(f"  {summary}", flush=True)
    print("", flush=True)


def _build_component_seeds(planner_output) -> List[TraceSeed]:
    seeds: List[TraceSeed] = []
    for component in planner_output.components:
        token = f"component:{component.name.lower().replace(' ', '_')}"
        aliases = {component.name, token}
        aliases.update(component.keywords or [])
        metadata = {"source": "planner"}
        if component.trace_tokens:
            metadata["trace_tokens"] = ",".join(component.trace_tokens)
        if component.evidence:
            metadata["evidence"] = "; ".join(component.evidence)
        seed = TraceSeed(
            token=token,
            kind="component",
            label=component.name,
            description=component.description,
            aliases=[alias for alias in aliases if alias],
            summary=component.description,
            metadata=metadata,
        )
        seeds.append(seed)
    return seeds


def _seeds_to_directories(seeds: Sequence[TraceSeed], directories: Sequence[DirectoryInsight]) -> List[DirectoryInsight]:
    lookup = {directory.directory_path: directory for directory in directories}
    results: List[DirectoryInsight] = []
    for seed in seeds:
        if seed.kind != "directory":
            continue
        directory = lookup.get(seed.directory_path or seed.token)
        if directory and directory not in results:
            results.append(directory)
    return results


def _seeds_to_profiles(seeds: Sequence[TraceSeed], profiles: Sequence[ProfileInsight]) -> List[ProfileInsight]:
    lookup = {profile.profile_id: profile for profile in profiles}
    results: List[ProfileInsight] = []
    for seed in seeds:
        if seed.kind != "profile":
            continue
        profile = lookup.get(seed.profile_id or seed.token)
        if profile and profile not in results:
            results.append(profile)
    return results


def _dedupe_directories(items: Sequence[DirectoryInsight]) -> List[DirectoryInsight]:
    seen = set()
    result = []
    for item in items:
        key = item.directory_path
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedupe_profiles(items: Sequence[ProfileInsight]) -> List[ProfileInsight]:
    seen = set()
    result = []
    for item in items:
        key = item.profile_id
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedupe_seeds(items: Sequence[TraceSeed]) -> List[TraceSeed]:
    seen = set()
    result = []
    for seed in items:
        if seed.token in seen:
            continue
        seen.add(seed.token)
        result.append(seed)
    return result


__all__ = ["build_top_down_graph"]
