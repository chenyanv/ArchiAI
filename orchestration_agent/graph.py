from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, TypedDict

from langgraph.graph import END, StateGraph

from tools.call_graph_pagerank import call_graph_pagerank_tool
from tools.list_core_models import list_core_models
from tools.list_entry_points import list_entry_point_tool

from .llm import LLMResponseError, invoke_llm
from .prompt import build_meta_prompt


class OrchestrationState(TypedDict, total=False):
    landmarks: List[Mapping[str, Any]]
    entry_points: List[Mapping[str, Any]]
    core_models: List[Mapping[str, Any]]
    entry_point_summary: str
    core_model_summary: str
    llm_response: str
    plan: Dict[str, Any]
    result: Dict[str, Any]


def _normalise_json_text(payload: Mapping[str, Any] | List[Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _core_model_fallback(core_models: Sequence[Mapping[str, Any]]) -> str:
    names: List[str] = []
    for model in core_models:
        name = (
            model.get("model_name")
            or model.get("name")
            or model.get("qualified_name")
        )
        if not name or name in names:
            continue
        names.append(str(name))

    top_models = names[:7]
    supporting = names[7:12]
    payload: Dict[str, Any] = {
        "top_models": top_models,
        "model_relationships": [],
    }
    if supporting:
        payload["supporting_models"] = supporting
    payload["notes"] = [
        "LLM summarisation unavailable; listing unique model identifiers."
    ]
    return _normalise_json_text(payload)


def _normalise_methods(methods: Iterable[Any]) -> List[str]:
    unique = {str(method).upper() for method in methods if method}
    return sorted(unique)


def _route_prefix(route: str) -> str:
    trimmed = route.strip()
    if not trimmed:
        return "/"

    stripped = trimmed.lstrip("/")
    if not stripped:
        return "/"

    segments = [segment for segment in stripped.split("/") if segment]
    if not segments:
        return "/"

    for segment in segments:
        if segment.startswith("<") and segment.endswith(">"):
            continue
        return f"/{segment}"

    # Fall back to the first segment (parameterised)
    return f"/{segments[0]}"


def _prefix_purpose(prefix: str) -> str:
    if prefix in {"", "/"}:
        return "Core root-level routes."

    token = prefix.strip("/").replace("_", " ").replace("-", " ").strip()
    if not token:
        return "Core root-level routes."
    return f"Routes handling {token} operations."


def _summarise_entry_points(entry_points: Sequence[Mapping[str, Any]]) -> str:
    if not entry_points:
        empty_payload = {
            "framework_totals": {},
            "route_groups": [],
            "noteworthy_routes": [],
            "notes": ["No HTTP entry points were detected."],
        }
        return _normalise_json_text(empty_payload)

    framework_counter: Counter[str] = Counter()
    route_aggregates: Dict[str, Dict[str, Any]] = {}

    for entry in entry_points:
        framework = entry.get("framework")
        if framework:
            framework_counter[str(framework)] += 1

        route_value = entry.get("route") or entry.get("path") or ""
        route = str(route_value).strip() or "/"
        aggregate = route_aggregates.setdefault(
            route,
            {
                "methods": set(),
                "handlers": set(),
                "file_paths": set(),
            },
        )

        methods = entry.get("http_methods") or entry.get("methods") or []
        aggregate["methods"].update(_normalise_methods(methods))

        handler = entry.get("qualified_name") or entry.get("symbol")
        if handler:
            aggregate["handlers"].add(str(handler))

        file_path = entry.get("file_path")
        if file_path:
            aggregate["file_paths"].add(str(file_path))

    grouped_routes: Dict[str, List[tuple[str, Dict[str, Any]]]] = defaultdict(list)
    for route, aggregate in route_aggregates.items():
        prefix = _route_prefix(route)
        grouped_routes[prefix].append((route, aggregate))

    def _sort_routes(items: List[tuple[str, Dict[str, Any]]]) -> List[tuple[str, Dict[str, Any]]]:
        return sorted(
            items,
            key=lambda item: (-len(item[1]["methods"]), item[0]),
        )

    sorted_groups = sorted(
        grouped_routes.items(),
        key=lambda item: (-len(item[1]), item[0]),
    )

    route_groups: List[Dict[str, Any]] = []
    used_routes: set[str] = set()
    for prefix, routes in sorted_groups[:6]:
        sorted_routes = _sort_routes(routes)
        payload_routes: List[Dict[str, Any]] = []
        for route, aggregate in sorted_routes[:6]:
            methods = sorted(aggregate["methods"])
            handlers = sorted(aggregate["handlers"])
            file_paths = sorted(aggregate["file_paths"])
            payload_routes.append(
                {
                    "path": route,
                    "methods": methods,
                    "handler": " | ".join(handlers),
                    "file_path": file_paths[0] if file_paths else "",
                }
            )
            used_routes.add(route)
        route_groups.append(
            {
                "prefix": prefix,
                "purpose": _prefix_purpose(prefix),
                "routes": payload_routes,
            }
        )

    noteworthy_candidates = [
        (route, aggregate)
        for route, aggregate in route_aggregates.items()
        if route not in used_routes
    ]
    noteworthy_sorted = sorted(
        noteworthy_candidates,
        key=lambda item: (-len(item[1]["methods"]), item[0]),
    )

    noteworthy_routes: List[Dict[str, Any]] = []
    for route, aggregate in noteworthy_sorted[:8]:
        methods = sorted(aggregate["methods"])
        handlers = sorted(aggregate["handlers"])
        file_paths = sorted(aggregate["file_paths"])
        noteworthy_routes.append(
            {
                "path": route,
                "methods": methods,
                "handler": " | ".join(handlers),
                "file_path": file_paths[0] if file_paths else "",
            }
        )

    payload: Dict[str, Any] = {
        "framework_totals": dict(framework_counter),
        "route_groups": route_groups,
        "noteworthy_routes": noteworthy_routes,
        "notes": ["Grouped by leading route segment to reduce noise."],
    }
    return _normalise_json_text(payload)


def _summarise_core_models(core_models: Sequence[Mapping[str, Any]]) -> str:
    if not core_models:
        empty_payload = {
            "top_models": [],
            "model_relationships": [],
            "supporting_models": [],
            "notes": ["No database models were detected."],
        }
        return _normalise_json_text(empty_payload)

    raw_models = json.dumps(core_models, ensure_ascii=False)
    summary_prompt = (
        "You are condensing database model inventory for an orchestration agent. "
        "Given the JSON list of models below, produce a concise JSON summary with "
        "the fields: top_models (<=7 strings), model_relationships (<=3 short "
        "sentences describing how the models interact), supporting_models (<=5 "
        "additional identifiers), and notes (optional short clarifications). "
        "Use exact identifiers from the input. Use [] when you have no evidence. "
        "Keep each sentence under 25 words.\n\n"
        "Input models JSON:\n"
        f"```json\n{raw_models}\n```"
    )

    try:
        response = invoke_llm(
            summary_prompt,
            temperature=0.0,
            max_output_tokens=512,
        )
    except LLMResponseError:
        return _core_model_fallback(core_models)

    for candidate in _iter_json_candidates(response):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (MutableMapping, list)):
            return _normalise_json_text(parsed)  # type: ignore[arg-type]

    return _core_model_fallback(core_models)


def _gather_intelligence(_: OrchestrationState) -> OrchestrationState:
    """
    Fetch the raw intelligence reports by invoking the three strategic tools.
    """
    landmarks = call_graph_pagerank_tool.invoke({"limit": 20})
    entry_points = list_entry_point_tool.invoke({"limit": 40})
    core_models = list_core_models.invoke({"limit": 50})
    return {
        "landmarks": landmarks or [],
        "entry_points": entry_points or [],
        "core_models": core_models or [],
    }


def _preprocess_intelligence(state: OrchestrationState) -> OrchestrationState:
    """
    Compress bulky intelligence (e.g. core models) before the main reasoning step.
    """
    entry_points: Sequence[Mapping[str, Any]] = state.get("entry_points", []) or []
    core_models: Sequence[Mapping[str, Any]] = state.get("core_models", []) or []
    entry_summary = _summarise_entry_points(entry_points)
    summary = _summarise_core_models(core_models)
    return {
        "entry_point_summary": entry_summary,
        "core_model_summary": summary,
    }


def _fuse_intelligence(state: OrchestrationState) -> OrchestrationState:
    """
    Feed the gathered intelligence to ChatGPT for high-level synthesis.
    """
    entry_points: Sequence[Mapping[str, Any]] = state.get("entry_points", []) or []
    core_models: Sequence[Mapping[str, Any]] = state.get("core_models", []) or []
    entry_summary = state.get("entry_point_summary")
    if not isinstance(entry_summary, str) or not entry_summary.strip():
        entry_summary = _summarise_entry_points(entry_points)
    core_summary = state.get("core_model_summary")
    if not isinstance(core_summary, str) or not core_summary.strip():
        core_summary = _summarise_core_models(core_models)

    prompt = build_meta_prompt(
        state.get("landmarks", []),
        entry_summary,
        len(entry_points),
        core_summary,
        len(core_models),
    )
    print("=== ORCHESTRATION PROMPT BEGIN ===")
    print(prompt)
    print("=== ORCHESTRATION PROMPT END ===")
    try:
        raw_response = invoke_llm(
            prompt,
            temperature=0.2,
            top_p=0.9,
            max_output_tokens=8192,
        )
    except LLMResponseError as exc:
        fallback = _fallback_plan(state, exc)
        return {
            "llm_response": str(exc),
            "plan": fallback,
        }

    plan = _parse_plan(raw_response)
    next_state: OrchestrationState = {
        "llm_response": raw_response,
    }
    if plan is not None:
        next_state["plan"] = plan
    return next_state


def _finalise(state: OrchestrationState) -> OrchestrationState:
    """
    Prepare the final payload for downstream consumers.
    """
    plan = state.get("plan")
    if plan is None:
        # When parsing fails, surface the raw response for manual handling.
        plan = {
            "system_overview": {
                "headline": "",
                "key_workflows": [],
            },
            "component_cards": [],
            "deprioritised_signals": [],
            "raw_response": state.get("llm_response"),
        }
    return {"result": plan}


def _parse_plan(response_text: str) -> Optional[Dict[str, Any]]:
    for candidate in _iter_json_candidates(response_text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, MutableMapping):
            return dict(parsed)
    return None


def _iter_json_candidates(response_text: str) -> Iterable[str]:
    """
    Yield progressively cleaned candidates that might contain the JSON payload.
    """
    stripped = response_text.strip()
    if stripped:
        yield stripped

    if stripped.startswith("```"):
        fence_match = re.match(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.S)
        if fence_match:
            inner = fence_match.group(1).strip()
            if inner:
                yield inner
        # Fallback: manually drop first/last lines if regex fails
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
            inner = "\n".join(lines[1:-1]).strip()
            if inner:
                yield inner

    # Generic fallback: grab text between the first { and the last }
    brace_match = re.search(r"\{.*\}", stripped, flags=re.S)
    if brace_match:
        candidate = brace_match.group(0).strip()
        if candidate:
            yield candidate


def _fallback_plan(state: OrchestrationState, error: LLMResponseError) -> Dict[str, Any]:
    metadata = getattr(error, "metadata", None)
    return {
        "system_overview": {
            "headline": "",
            "key_workflows": [],
        },
        "component_cards": [],
        "deprioritised_signals": [],
        "error": {
            "type": error.__class__.__name__,
            "message": str(error),
            "metadata": metadata,
            "landmark_count": len(state.get("landmarks", []) or []),
            "entry_point_count": len(state.get("entry_points", []) or []),
            "core_model_count": len(state.get("core_models", []) or []),
        },
    }


def build_orchestration_agent() -> StateGraph:
    """
    Construct the LangGraph agent responsible for orchestration planning.
    """
    workflow = StateGraph(OrchestrationState)
    workflow.add_node("gather_intelligence", _gather_intelligence)
    workflow.add_node("preprocess_intelligence", _preprocess_intelligence)
    workflow.add_node("intelligence_fusion", _fuse_intelligence)
    workflow.add_node("finalise", _finalise)

    workflow.set_entry_point("gather_intelligence")
    workflow.add_edge("gather_intelligence", "preprocess_intelligence")
    workflow.add_edge("preprocess_intelligence", "intelligence_fusion")
    workflow.add_edge("intelligence_fusion", "finalise")
    workflow.add_edge("finalise", END)

    return workflow.compile()


def run_orchestration_agent(initial_state: Optional[OrchestrationState] = None) -> Dict[str, Any]:
    """
    Convenience helper to execute the compiled graph and return the final plan.
    """
    graph = build_orchestration_agent()
    default_state: OrchestrationState = {
        "landmarks": [],
        "entry_points": [],
        "core_models": [],
    }
    state: OrchestrationState = default_state
    if initial_state:
        state.update(initial_state)
    final_state = graph.invoke(state)
    return final_state.get("result", {})
