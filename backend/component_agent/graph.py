"""LangGraph workflow powering the component drilldown sub-agent."""

from __future__ import annotations

import json
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

from llm_logger import get_llm_logger

from .llm import build_component_chat_model
from .prompt import build_component_system_prompt, format_component_request
from .schemas import ComponentDrilldownRequest, ComponentDrilldownResponse, TokenMetrics
from .token_tracker import TokenTracker
from .toolkit import build_workspace_tools


LogFn = Callable[[str], None]
ToolLogFn = Callable[[str, Dict[str, Any], Any], None]
LLMContextLogger = Callable[[List[Dict[str, Any]]], None]


class Phase(str, Enum):
    """Explicit phase constants for Scout-Drill workflow.

    This allows code and prompts to refer to phases by a single, authoritative source.
    """
    SCOUT = "scout"  # Phase 1: Pattern recognition and tool calling
    DRILL = "drill"  # Phase 2: Synthesis and output generation


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
    """Executes tool calls from LLM and returns results via ToolMessage.

    Properly maintains message stack protocol: ToolMessage always follows
    the AIMessage that requested the tool call.
    """
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
    tools: Sequence[BaseTool],
    temperature: float = 0.0,
    logger: Optional[LogFn] = None,
    debug: bool = False,
    tool_logger: Optional[ToolLogFn] = None,
    llm_context_logger: Optional[LLMContextLogger] = None,
):
    model = build_component_chat_model(temperature=temperature)
    toolset = list(tools)
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


def _extract_pattern_from_scout_output(scout_message: AIMessage) -> Optional[Dict[str, Any]]:
    """Extract and validate pattern identification from Scout's final AI message.

    Scout should output a JSON structure containing scout_pattern_identification.
    This function:
    1. Extracts JSON from Scout's message content
    2. Validates required fields
    3. Validates pattern_type is A, B, or C
    4. Returns validated pattern data or None

    Returns:
        Dict with validated pattern_type, confidence, reasoning, etc., or None if invalid.
    """
    try:
        content = _coerce_text(scout_message.content)

        if not content or len(content) < 50:
            # Content too short to contain valid JSON
            return None

        # Look for the scout_pattern_identification JSON block
        # It may be embedded in the message text
        start_idx = content.find('"scout_pattern_identification"')
        if start_idx == -1:
            # Try looking for JSON object marker
            start_idx = content.find('{')
            if start_idx == -1:
                return None

        # Find the matching closing brace
        brace_count = 0
        in_string = False
        escape_next = False
        end_idx = start_idx

        for i in range(start_idx, len(content)):
            char = content[i]

            if escape_next:
                escape_next = False
                continue

            if char == '\\':
                escape_next = True
                continue

            if char == '"' and (i == 0 or content[i-1] != '\\'):
                in_string = not in_string
                continue

            if not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break

        if brace_count != 0:
            return None

        json_str = content[start_idx:end_idx]
        parsed = json.loads(json_str)

        # Extract the pattern_identification structure
        pattern_data = parsed.get("scout_pattern_identification")
        if not pattern_data:
            # If the JSON is the pattern_identification itself
            if "pattern_type" in parsed:
                pattern_data = parsed
            else:
                return None

        # Validate required fields
        if not isinstance(pattern_data, dict):
            return None

        pattern_type = pattern_data.get("pattern_type")
        confidence = pattern_data.get("confidence")
        reasoning = pattern_data.get("reasoning")
        tools_called = pattern_data.get("tools_called")

        # Validate pattern_type is A, B, or C
        if pattern_type not in ("A", "B", "C"):
            return None

        # Validate confidence is a number between 0 and 1
        if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 1):
            return None

        # Validate reasoning is a string
        if not isinstance(reasoning, str) or not reasoning.strip():
            return None

        # Validate tools_called is a list
        if not isinstance(tools_called, list) or len(tools_called) == 0:
            return None

        # All validations passed - return the validated pattern data
        return pattern_data

    except (json.JSONDecodeError, ValueError, IndexError, TypeError):
        # Pattern extraction failed, will use generic Drill prompt
        return None


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
    token_tracker: Optional[TokenTracker] = None,
) -> ComponentDrilldownResponse:
    """Execute the component analysis agent with proper ReAct architecture.

    Both Scout and Drill phases operate as autonomous ReAct agents:
    - Scout: Analyzes component and calls tools autonomously to gather evidence
    - Drill: Reasons through Scout findings and synthesizes structured response

    No explicit phase injection or fake messages needed - proper message stack protocol.
    """

    # Get logger instance for file-based logging
    llm_logger = get_llm_logger()

    # Create or reuse token tracker for both Scout and Drill phases
    if token_tracker is None:
        token_tracker = TokenTracker()

    # Build tools dynamically for the workspace if not provided
    toolset = list(tools) if tools else build_workspace_tools(request.workspace_id, request.database_url)
    graph = build_component_agent(
        tools=toolset,
        temperature=temperature,
        logger=logger,
        debug=debug,
        tool_logger=log_tool_usage,
        llm_context_logger=log_llm_input,
    )

    # === PHASE 1: SCOUT - Autonomous pattern analysis with tool exploration ===
    if debug and logger:
        logger("[scout:phase:start] Beginning SCOUT phase - autonomous pattern analysis")

    # Determine focus node type for context-aware Scout strategy
    focus_node_type = None
    if request.breadcrumbs:
        # If we have breadcrumbs, we're drilling into a specific node
        # Get the type of the deepest (current) node
        current_focus = request.breadcrumbs[-1]
        focus_node_type = current_focus.node_type
        if debug and logger:
            logger(f"[scout:focus] Drilling into {focus_node_type} node: {current_focus.title}")

    scout_system_message = SystemMessage(
        content=build_component_system_prompt(phase=Phase.SCOUT.value, focus_node_type=focus_node_type)
    )
    scout_human_message = HumanMessage(
        content=format_component_request(request)
    )

    # Log initial state for PHASE 1
    scout_messages: List[BaseMessage] = [scout_system_message, scout_human_message]
    serialized_scout_messages = _serialise_messages_for_log(scout_messages)

    # Log the Scout phase invocation with context
    llm_logger.log_invocation(
        label="[COMPONENT_AGENT_SCOUT]",
        messages=serialized_scout_messages,
        workspace_id=request.workspace_id,
        cache_id=getattr(request, "cache_id", None),
        breadcrumbs=list(request.breadcrumbs) if request.breadcrumbs else None,
    )

    # Run the ReAct loop - Scout is autonomous, calls tools as needed
    scout_start_time = time.time()
    scout_final_state = graph.invoke({"messages": scout_messages})
    scout_duration_ms = (time.time() - scout_start_time) * 1000

    # Log Scout phase completion
    scout_final_serialized = _serialise_messages_for_log(scout_final_state["messages"])
    scout_last_message = scout_final_state["messages"][-1] if scout_final_state["messages"] else None
    llm_logger.log_response(
        label="[COMPONENT_AGENT_SCOUT]",
        response=scout_last_message,
        duration_ms=scout_duration_ms,
    )

    # Track tokens from Scout's ReAct loop
    if token_tracker:
        token_tracker.track_messages(scout_final_state["messages"])

    # Record Scout phase token usage for diagnostics
    scout_prompt_tokens = token_tracker.total_prompt_tokens
    scout_completion_tokens = token_tracker.total_completion_tokens
    scout_total_tokens = token_tracker.total_tokens

    if debug and logger:
        logger("[scout:phase:end] Scout phase completed")
        scout_content_preview = _coerce_text(scout_last_message.content)[:300] if scout_last_message else ""
        logger(f"[scout:output:preview] {scout_content_preview}...")
        logger(f"[scout:tokens] Scout used: {scout_total_tokens} total ({scout_prompt_tokens} input + {scout_completion_tokens} output)")

    # === PHASE 2: DRILL - Autonomous synthesis from Scout findings ===
    if debug and logger:
        logger("[drill:phase:start] Beginning DRILL phase - autonomous synthesis")

    # Determine which Drill prompt to use based on Scout's findings
    # (This is pattern routing, but discovery-based not code-driven)
    pattern_type = None
    pattern_data = None

    if isinstance(scout_last_message, AIMessage):
        pattern_data = _extract_pattern_from_scout_output(scout_last_message)
        if pattern_data:
            pattern_type = pattern_data.get("pattern_type")
            if debug and logger:
                confidence = pattern_data.get("confidence", "?")
                logger(f"[drill:pattern:identified] Pattern: {pattern_type} (confidence: {confidence})")
        else:
            if debug and logger:
                logger("[drill:pattern:not-found] Using generic Drill prompt")

    # Build Drill phase messages using Scout's conclusion only
    # OPTIMIZATION: Only pass Scout's final AI response + original component context
    # This reduces token usage and speeds up Drill phase (was: passing all Scout messages)
    drill_system_message = SystemMessage(
        content=build_component_system_prompt(phase=Phase.DRILL.value, pattern=pattern_type, focus_node_type=focus_node_type)
    )

    # Extract Scout's initial human message (component context) - needed for Drill to understand what was analyzed
    scout_human_message = None
    for msg in scout_final_state["messages"]:
        if isinstance(msg, HumanMessage):
            scout_human_message = msg
            break  # Get the first HumanMessage (the original request)

    # Extract Scout's final AI message (the conclusion with findings)
    scout_final_conclusion = None
    for msg in reversed(scout_final_state["messages"]):
        if isinstance(msg, AIMessage):
            scout_final_conclusion = msg
            break  # Get the last AIMessage (Scout's final synthesis)

    # Build Drill messages with minimal but sufficient context
    # Drill needs: system prompt, original component context, Scout's final conclusion
    drill_messages: List[BaseMessage] = [drill_system_message]
    if scout_human_message:
        drill_messages.append(scout_human_message)
    if scout_final_conclusion:
        drill_messages.append(scout_final_conclusion)

    if debug and logger:
        msg_count = len([m for m in drill_messages if not isinstance(m, SystemMessage)])
        logger(f"[drill:context] OPTIMIZED: Using only Scout's conclusion + initial context ({msg_count} messages)")
        logger(f"[drill:context:saved-tokens] Removed {len(scout_final_state['messages']) - msg_count} intermediate Scout messages")

    # Use structured output to generate the final response
    # Drill will synthesize based on Scout's findings
    model = build_component_chat_model(temperature=temperature)
    structured_model = model.with_structured_output(
        ComponentDrilldownResponse,
        method="json_schema",
        include_raw=True,
    )

    # Log the Drill phase invocation
    drill_serialized = _serialise_messages_for_log(drill_messages)
    llm_logger.log_invocation(
        label="[COMPONENT_AGENT_DRILL]",
        messages=drill_serialized,
        workspace_id=request.workspace_id,
        cache_id=getattr(request, "cache_id", None),
    )

    # Run Drill synthesis
    drill_start_time = time.time()
    result = structured_model.invoke(drill_messages)
    drill_duration_ms = (time.time() - drill_start_time) * 1000

    if debug and logger:
        logger("[drill:synthesis:complete] Structured output generated")

    # Log Drill phase completion
    raw_message = result.get("raw")
    llm_logger.log_response(
        label="[COMPONENT_AGENT_DRILL]",
        response=raw_message if raw_message else result,
        duration_ms=drill_duration_ms,
    )

    # Extract parsed response
    # include_raw=True returns a dict with 'raw' (AIMessage) and 'parsed' (Pydantic object)
    response: ComponentDrilldownResponse = result.get("parsed")

    if token_tracker and raw_message:
        token_tracker.track_messages([raw_message])

    # Record Drill phase token usage for diagnostics
    drill_prompt_tokens = token_tracker.total_prompt_tokens - scout_prompt_tokens
    drill_completion_tokens = token_tracker.total_completion_tokens - scout_completion_tokens
    drill_total_tokens = token_tracker.total_tokens - scout_total_tokens

    if debug and logger:
        logger(f"[drill:tokens] Drill used: {drill_total_tokens} total ({drill_prompt_tokens} input + {drill_completion_tokens} output)")

    # Fill in missing fields if needed
    if not response.component_id:
        response.component_id = str(request.component_card.get("component_id", ""))
    if not response.breadcrumbs and request.breadcrumbs:
        response.breadcrumbs = list(request.breadcrumbs)

    if debug and logger:
        logger(f"[drill:phase:end] Generated response with {len(response.next_layer.nodes)} nodes")

    # === Calculate token metrics from both Scout and Drill phases ===
    total_prompt_tokens = token_tracker.total_prompt_tokens
    total_completion_tokens = token_tracker.total_completion_tokens
    total_tokens = token_tracker.total_tokens

    # Calculate estimated cost (Gemini pricing: 0.075/M input, 0.30/M output)
    estimated_cost = (total_prompt_tokens * 0.075 + total_completion_tokens * 0.30) / 1_000_000

    if total_tokens > 0:
        token_metrics = TokenMetrics(
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            total_tokens=total_tokens,
            estimated_cost=round(estimated_cost, 6)
        )
        response.token_metrics = token_metrics

        if debug and logger:
            logger(f"[tokens] TOTAL: {total_tokens} tokens ({total_prompt_tokens} input + {total_completion_tokens} output)")
            logger(f"[tokens] Breakdown -> Scout: {scout_total_tokens}, Drill: {drill_total_tokens} | Cost: ${estimated_cost:.6f}")

    # TODO: Verify that LLM correctly populates semantic_metadata for each node when prompted.
    # The Drill phase prompts (Pattern A/B/C and class-level) now include semantic extraction guidance.
    # Monitor LLM responses to ensure semantic_metadata fields (semantic_role, business_context,
    # flow_position, risk_level, impacted_workflows, business_narrative) are consistently populated.

    return response


__all__ = ["Phase", "build_component_agent", "run_component_agent"]
