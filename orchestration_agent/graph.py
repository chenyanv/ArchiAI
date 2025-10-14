from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, TypedDict

from langgraph.graph import END, StateGraph

from tools.call_graph_pagerank import call_graph_pagerank_tool
from tools.list_core_models import list_core_models
from tools.list_entry_points import list_entry_point_tool

from .llm import ChatGPTResponseError, invoke_chatgpt
from .prompt import build_meta_prompt


class OrchestrationState(TypedDict, total=False):
    landmarks: List[Mapping[str, Any]]
    entry_points: List[Mapping[str, Any]]
    core_models: List[Mapping[str, Any]]
    llm_response: str
    plan: Dict[str, Any]
    result: Dict[str, Any]


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


def _fuse_intelligence(state: OrchestrationState) -> OrchestrationState:
    """
    Feed the gathered intelligence to ChatGPT for high-level synthesis.
    """
    prompt = build_meta_prompt(
        state.get("landmarks", []),
        state.get("entry_points", []),
        state.get("core_models", []),
    )
    try:
        raw_response = invoke_chatgpt(
            prompt,
            temperature=0.2,
            top_p=0.9,
            max_output_tokens=2048,
        )
    except ChatGPTResponseError as exc:
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
            "business_logic_summary": "",
            "key_domains": [],
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


def _fallback_plan(state: OrchestrationState, error: ChatGPTResponseError) -> Dict[str, Any]:
    metadata = getattr(error, "metadata", None)
    return {
        "business_logic_summary": "",
        "key_domains": [],
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
    workflow.add_node("intelligence_fusion", _fuse_intelligence)
    workflow.add_node("finalise", _finalise)

    workflow.set_entry_point("gather_intelligence")
    workflow.add_edge("gather_intelligence", "intelligence_fusion")
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
