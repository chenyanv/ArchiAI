"""LangGraph workflow powering the component drilldown sub-agent."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

from .llm import build_component_chat_model
from .prompt import build_component_system_prompt, format_component_request
from .schemas import ComponentDrilldownRequest, ComponentDrilldownResponse
from .toolkit import DEFAULT_SUBAGENT_TOOLS, summarise_tools


LogFn = Callable[[str], None]
ToolLogFn = Callable[[str, Dict[str, Any], Any], None]
LLMContextLogger = Callable[[List[Dict[str, Any]]], None]


class ComponentAgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]


def _call_model(
    model,
    logger: Optional[LogFn] = None,
    debug: bool = False,
    context_logger: Optional[LLMContextLogger] = None,
):
    def _invoke(state: ComponentAgentState) -> ComponentAgentState:
        if context_logger:
            try:
                context_logger(_serialise_messages_for_log(state["messages"]))
            except Exception:  # pragma: no cover - logging is best-effort
                if debug and logger:
                    logger("[llm:logger-error] context_logger raised unexpectedly.")
        if debug and logger:
            logger("[llm:input] ingesting %d messages" % len(state["messages"]))
        response = model.invoke(state["messages"])
        if debug and logger:
            preview = _coerce_text(response.content)
            logger(f"[llm:output] finish_reason={(getattr(response, 'response_metadata', {}) or {}).get('finish_reason')}\n{preview}")
        return {"messages": [response]}

    return _invoke


def _should_continue(state: ComponentAgentState) -> str:
    last: BaseMessage = state["messages"][-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tool"
    return "end"


class InstrumentedToolNode:
    def __init__(
        self,
        tools: Sequence[BaseTool],
        logger: Optional[LogFn] = None,
        debug: bool = False,
        tool_logger: Optional[ToolLogFn] = None,
    ):
        self.tools = {tool.name: tool for tool in tools}
        self.logger = logger
        self.debug = debug
        self.tool_logger = tool_logger

    def __call__(self, state: ComponentAgentState) -> ComponentAgentState:
        outputs: List[ToolMessage] = []
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None) or []

        for tool_call in tool_calls:
            name = tool_call.get("name")
            if not name:
                continue
            tool = self.tools.get(name)
            if tool is None:
                continue
            args = tool_call.get("args") or {}
            if self.debug and self.logger:
                self.logger(f"[tool:start] {name} args={_safe_json(args)}")
            result = tool.invoke(args)
            if self.debug and self.logger:
                self.logger(f"[tool:end] {name} result={_truncate(_safe_json(result))}")
            if self.tool_logger:
                try:
                    self.tool_logger(name, args, result)
                except Exception:  # pragma: no cover - logging must not break execution
                    if self.debug and self.logger:
                        self.logger("[tool:logger-error] tool_logger raised unexpectedly.")
            outputs.append(
                ToolMessage(
                    content=_safe_json(result),
                    tool_call_id=tool_call.get("id"),
                )
            )
        return {"messages": outputs}


def build_component_agent(
    *,
    tools: Optional[Sequence[BaseTool]] = None,
    temperature: float = 0.0,
    logger: Optional[LogFn] = None,
    debug: bool = False,
    tool_logger: Optional[ToolLogFn] = None,
    llm_context_logger: Optional[LLMContextLogger] = None,
):
    model = build_component_chat_model(temperature=temperature)
    toolset = list(tools or DEFAULT_SUBAGENT_TOOLS)
    model_with_tools = model.bind_tools(toolset)

    workflow = StateGraph(ComponentAgentState)
    workflow.add_node(
        "agent",
        _call_model(
            model_with_tools,  # Use model with bound tools
            logger=logger,
            debug=debug,
            context_logger=llm_context_logger,
        ),
    )
    workflow.add_node(
        "tool_node",
        InstrumentedToolNode(toolset, logger=logger, debug=debug, tool_logger=tool_logger),
    )
    workflow.add_conditional_edges(
        "agent",
        _should_continue,
        {
            "tool": "tool_node",
            "end": END,
        },
    )
    workflow.add_edge("tool_node", "agent")
    workflow.set_entry_point("agent")
    return workflow.compile()


def _coerce_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        fragments: List[str] = []
        for chunk in content:
            if isinstance(chunk, str):
                fragments.append(chunk)
            elif isinstance(chunk, Mapping):
                text = chunk.get("text")
                if text:
                    fragments.append(str(text))
        return "\n".join(fragments)
    return str(content)


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return repr(value)


def _truncate(value: str, limit: int = 600) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…"


def _serialise_messages_for_log(
    messages: Sequence[BaseMessage],
) -> List[Dict[str, Any]]:
    serialised: List[Dict[str, Any]] = []
    for index, message in enumerate(messages, start=1):
        entry: Dict[str, Any] = {
            "index": index,
            "type": message.__class__.__name__,
            "content": _coerce_text(getattr(message, "content", "")),
        }
        additional = getattr(message, "additional_kwargs", None)
        if additional:
            entry["additional_kwargs"] = additional
        if isinstance(message, AIMessage):
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                entry["tool_calls"] = tool_calls
        if isinstance(message, ToolMessage):
            entry["tool_call_id"] = message.tool_call_id
        serialised.append(entry)
    return serialised


def run_component_agent(
    request: ComponentDrilldownRequest,
    *,
    tools: Optional[Sequence[BaseTool]] = None,
    temperature: float = 0.0,
    max_retries: int = 3,
    debug: bool = False,
    logger: Optional[LogFn] = None,
    log_tool_usage: Optional[ToolLogFn] = None,
    log_llm_input: Optional[LLMContextLogger] = None,
) -> ComponentDrilldownResponse:
    """Execute the sub-agent and return a structured drilldown response."""

    toolset = list(tools or DEFAULT_SUBAGENT_TOOLS)
    graph = build_component_agent(
        tools=toolset,
        temperature=temperature,
        logger=logger,
        debug=debug,
        tool_logger=log_tool_usage,
        llm_context_logger=log_llm_input,
    )
    system_message = SystemMessage(content=build_component_system_prompt())
    tool_catalog = summarise_tools(toolset)
    human_message = HumanMessage(
        content=format_component_request(request, tool_catalog=tool_catalog)
    )

    # Run the ReAct loop to gather tool information
    messages: List[BaseMessage] = [system_message, human_message]
    final_state = graph.invoke({"messages": messages})

    # Use structured output to generate the final response
    # This leverages Gemini's native JSON schema enforcement
    model = build_component_chat_model(temperature=temperature)
    structured_model = model.with_structured_output(
        ComponentDrilldownResponse,
        method="json_schema",
    )

    if debug and logger:
        logger("[structured_output] Generating ComponentDrilldownResponse from conversation")

    response: ComponentDrilldownResponse = structured_model.invoke(final_state["messages"])

    # Fill in missing fields if needed
    if not response.component_id:
        response.component_id = str(request.component_card.get("component_id", ""))
    if not response.breadcrumbs and request.breadcrumbs:
        response.breadcrumbs = list(request.breadcrumbs)

    if debug and logger:
        logger(f"[structured_output:success] Generated response with {len(response.next_layer.nodes)} nodes")

    return response


__all__ = ["build_component_agent", "run_component_agent"]
