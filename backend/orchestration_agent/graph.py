"""LangGraph workflow powering the orchestration agent (ReAct pattern)."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import Annotated, TypedDict

from llm_logger import get_llm_logger

from .llm import build_orchestration_chat_model
from .prompt import build_orchestration_system_prompt, build_orchestration_user_prompt
from .schemas import OrchestrationResponse
from .toolkit import build_orchestration_tools


LogFn = Callable[[str], None]


class AgentState(TypedDict):
    """State for the orchestration agent ReAct loop."""

    messages: Annotated[List[BaseMessage], add_messages]


def _coerce_text(content: Any) -> str:
    """Extract text from various content formats."""
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
        fragments = []
        for chunk in content:
            if isinstance(chunk, str):
                fragments.append(chunk)
            elif isinstance(chunk, dict) and (text := chunk.get("text")):
                fragments.append(str(text))
        return "\n".join(fragments)
    return str(content)


def _safe_json(value: Any) -> str:
    """Safely serialize a value to JSON."""
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return repr(value)


def _truncate(text: str, limit: int = 600) -> str:
    """Truncate a string to a maximum length."""
    return text if len(text) <= limit else text[:limit] + "…"


def _parse_json_from_response(response_text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON from the LLM response."""
    stripped = response_text.strip()

    # Try direct parse
    try:
        if isinstance(parsed := json.loads(stripped), dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Try extracting from code fence
    if fence_match := re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.S):
        try:
            if isinstance(parsed := json.loads(fence_match.group(1).strip()), dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # Try extracting any JSON object
    if brace_match := re.search(r"\{.*\}", stripped, flags=re.S):
        try:
            if isinstance(parsed := json.loads(brace_match.group(0)), dict):
                return parsed
        except json.JSONDecodeError:
            pass

    return None


def _create_agent_node(model, logger: Optional[LogFn] = None, debug: bool = False):
    """Create a node that invokes the LLM."""

    def invoke(state: AgentState) -> AgentState:
        if debug and logger:
            logger(f"[llm:input] ingesting {len(state['messages'])} messages")
        response = model.invoke(state["messages"])
        if debug and logger:
            preview = _coerce_text(response.content)[:500]
            finish_reason = (getattr(response, "response_metadata", {}) or {}).get("finish_reason")
            logger(f"[llm:output] finish_reason={finish_reason}\n{preview}...")
        return {"messages": [response]}

    return invoke


def _create_tool_node(tools: Sequence[BaseTool], logger: Optional[LogFn] = None, debug: bool = False):
    """Create a tool node with optional logging."""
    tool_map = {tool.name: tool for tool in tools}
    base_node = ToolNode(tools)

    def invoke(state: AgentState) -> AgentState:
        if not debug or not logger:
            return base_node.invoke(state)

        # Manual execution with logging
        outputs: List[ToolMessage] = []
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None) or []

        for call in tool_calls:
            name, args = call.get("name"), call.get("args") or {}
            if not name:
                continue

            tool = tool_map.get(name)
            if tool is None:
                outputs.append(ToolMessage(content=f"Error: Tool '{name}' not found", tool_call_id=call.get("id")))
                continue

            logger(f"[tool:start] {name} args={_safe_json(args)}")
            try:
                result = tool.invoke(args)
            except Exception as exc:
                result = {"error": str(exc)}
            logger(f"[tool:end] {name} result={_truncate(_safe_json(result))}")

            outputs.append(ToolMessage(content=_safe_json(result), tool_call_id=call.get("id")))

        return {"messages": outputs}

    return invoke


def _should_continue(state: AgentState) -> str:
    """Determine if the agent should continue calling tools or end."""
    last: BaseMessage = state["messages"][-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tools"
    return END


def build_orchestration_graph(
    tools: Sequence[BaseTool],
    *,
    temperature: float = 0.2,
    logger: Optional[LogFn] = None,
    debug: bool = False,
):
    """Build the orchestration agent graph with ReAct pattern."""
    model = build_orchestration_chat_model(temperature=temperature).bind_tools(tools)

    graph = StateGraph(AgentState)
    graph.add_node("agent", _create_agent_node(model, logger, debug))
    graph.add_node("tools", _create_tool_node(tools, logger, debug))
    graph.add_conditional_edges("agent", _should_continue, ["tools", END])
    graph.add_edge("tools", "agent")
    graph.set_entry_point("agent")

    return graph.compile()


def run_orchestration_agent(
    workspace_id: str,
    database_url: str | None = None,
    *,
    tools: Optional[Sequence[BaseTool]] = None,
    temperature: float = 0.2,
    debug: bool = False,
    logger: Optional[LogFn] = None,
) -> Dict[str, Any]:
    """Execute the orchestration agent and return the architecture analysis."""
    # Get logger instance for file-based logging
    llm_logger = get_llm_logger()

    toolset = list(tools) if tools else build_orchestration_tools(workspace_id, database_url)

    graph = build_orchestration_graph(toolset, temperature=temperature, logger=logger, debug=debug)

    initial_messages = [
        SystemMessage(content=build_orchestration_system_prompt()),
        HumanMessage(content=build_orchestration_user_prompt(workspace_id)),
    ]

    if debug and logger:
        logger("[orchestration] Starting ReAct loop...")

    # === Log orchestration agent invocation ===
    # Helper function to serialize messages for logging
    def _serialise_for_log(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
        serialised = []
        for index, message in enumerate(messages, start=1):
            entry: Dict[str, Any] = {
                "index": index,
                "type": message.__class__.__name__,
                "content": _coerce_text(getattr(message, "content", "")),
            }
            if isinstance(message, AIMessage):
                tool_calls = getattr(message, "tool_calls", None)
                if tool_calls:
                    entry["tool_calls"] = tool_calls
            serialised.append(entry)
        return serialised

    serialized_messages = _serialise_for_log(initial_messages)
    llm_logger.log_invocation(
        label="[ORCHESTRATION_AGENT]",
        messages=serialized_messages,
        workspace_id=workspace_id,
    )

    orchestration_start_time = time.time()
    final_state = graph.invoke({"messages": initial_messages}, {"recursion_limit": 50})
    orchestration_duration_ms = (time.time() - orchestration_start_time) * 1000

    # Log orchestration response
    final_response = final_state["messages"][-1] if final_state["messages"] else None
    llm_logger.log_response(
        label="[ORCHESTRATION_AGENT]",
        response=final_response,
        duration_ms=orchestration_duration_ms,
    )

    if debug and logger:
        logger(f"[orchestration] ReAct loop completed with {len(final_state['messages'])} messages")

    # Parse and validate the response
    response_text = _coerce_text(final_state["messages"][-1].content)
    parsed = _parse_json_from_response(response_text)

    if parsed:
        try:
            return OrchestrationResponse.model_validate(parsed).model_dump()
        except Exception as exc:
            if debug and logger:
                logger(f"[orchestration] Schema validation failed: {exc}")
            return parsed

    if debug and logger:
        logger("[orchestration] Failed to parse JSON from response")

    return {
        "system_overview": {"headline": "Analysis could not be parsed", "key_workflows": []},
        "component_cards": [],
        "deprioritised_signals": [],
        "raw_response": response_text,
    }


__all__ = ["build_orchestration_graph", "run_orchestration_agent"]
