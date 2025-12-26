"""LLM prompt logging system for debugging agent behavior."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _safe_json(value: Any) -> str:
    """Safely serialize a value to JSON."""
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        return repr(value)


class LLMPromptLogger:
    """Log full LLM prompts to files with proper labels and context."""

    def __init__(self, log_dir: str = "logs"):
        """Initialize logger with log directory."""
        self.log_dir = log_dir
        # Create logs directory if it doesn't exist
        Path(self.log_dir).mkdir(exist_ok=True, parents=True)

    def _get_log_file(self, prefix: str = "agent_prompts") -> str:
        """Get log file path with date suffix."""
        today = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.log_dir, f"{prefix}_{today}.log")

    def _write_log(self, content: str, log_file: str) -> None:
        """Write content to log file (append mode)."""
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(content)
                f.write("\n")
        except Exception as e:
            # Logging should not break execution
            print(f"[LLMLogger Warning] Failed to write log: {e}", flush=True)

    def log_invocation(
        self,
        label: str,
        messages: List[Dict[str, Any]],
        workspace_id: Optional[str] = None,
        cache_id: Optional[str] = None,
        breadcrumbs: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Log LLM invocation with full messages and context.

        Args:
            label: Label for this invocation (e.g., [COMPONENT_AGENT_SCOUT])
            messages: List of message dicts from _serialise_messages_for_log()
            workspace_id: Optional workspace ID for context
            cache_id: Optional cache ID for context
            breadcrumbs: Optional breadcrumb trail for context
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_file = self._get_log_file("agent_prompts")

        # Build log entry
        lines = []
        lines.append("\n" + "=" * 100)
        lines.append(f"[{timestamp}] {label}")

        if workspace_id or cache_id:
            context_parts = []
            if workspace_id:
                context_parts.append(f"workspace={workspace_id}")
            if cache_id:
                context_parts.append(f"cache_id={cache_id}")
            lines.append(f"Context: {' '.join(context_parts)}")

        lines.append("=" * 100)

        # Log messages with proper formatting
        lines.append(f"\nMESSAGES ({len(messages)} total):")
        lines.append("-" * 100)

        for msg in messages:
            msg_type = msg.get("type", "unknown")
            msg_index = msg.get("index", "?")
            content = msg.get("content", "")

            # Format content (truncate if very long)
            if isinstance(content, str) and len(content) > 2000:
                content_preview = content[:2000] + "\n... (truncated)"
            else:
                content_preview = content

            lines.append(f"\nMessage #{msg_index} [{msg_type}]:")

            # Display content
            if isinstance(content_preview, str):
                lines.append(content_preview)
            else:
                lines.append(_safe_json(content_preview))

            # Display tool calls if present
            if "tool_calls" in msg and msg["tool_calls"]:
                lines.append(f"  Tool calls: {_safe_json(msg['tool_calls'])}")

        # Log breadcrumbs if present
        if breadcrumbs:
            lines.append("\n" + "-" * 100)
            lines.append(f"\nBREADCRUMBS (depth={len(breadcrumbs)}):")
            lines.append(_safe_json(breadcrumbs))

        lines.append("\n" + "=" * 100)

        # Write to file
        log_content = "\n".join(lines)
        self._write_log(log_content, log_file)

    def log_response(
        self,
        label: str,
        response: Any,
        duration_ms: Optional[float] = None,
        token_count: Optional[Dict[str, int]] = None,
    ) -> None:
        """Log LLM response.

        Args:
            label: Label for this response (e.g., [COMPONENT_AGENT_SCOUT])
            response: The AI response object
            duration_ms: Optional execution time in milliseconds
            token_count: Optional dict with input/output token counts
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_file = self._get_log_file("agent_prompts")

        lines = []
        lines.append(f"\n[{timestamp}] {label} RESPONSE")
        lines.append("-" * 100)

        # Extract content
        content = getattr(response, "content", "")
        if isinstance(content, str):
            response_preview = content[:2000] + ("... (truncated)" if len(content) > 2000 else "")
        else:
            response_preview = _safe_json(content)[:2000]

        lines.append(response_preview)

        # Log metadata
        if duration_ms is not None:
            lines.append(f"\nDuration: {duration_ms:.1f}ms")

        if token_count:
            lines.append(f"Tokens - Input: {token_count.get('input', 0)}, Output: {token_count.get('output', 0)}")

        # Log finish reason if available
        finish_reason = (getattr(response, "response_metadata", {}) or {}).get("finish_reason")
        if finish_reason:
            lines.append(f"Finish reason: {finish_reason}")

        lines.append("=" * 100)

        log_content = "\n".join(lines)
        self._write_log(log_content, log_file)

    def log_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Any,
        duration_ms: Optional[float] = None,
    ) -> None:
        """Log tool invocation and result.

        Args:
            tool_name: Name of the tool
            args: Input arguments to the tool
            result: Result from the tool
            duration_ms: Optional execution time in milliseconds
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_file = self._get_log_file("tool_calls")

        lines = []
        lines.append(f"\n[{timestamp}] TOOL CALL: {tool_name}")
        lines.append("-" * 100)

        lines.append("Arguments:")
        lines.append(_safe_json(args))

        lines.append("\nResult:")
        result_preview = _safe_json(result)[:2000]
        lines.append(result_preview + ("... (truncated)" if len(_safe_json(result)) > 2000 else ""))

        if duration_ms is not None:
            lines.append(f"\nDuration: {duration_ms:.1f}ms")

        lines.append("=" * 100)

        log_content = "\n".join(lines)
        self._write_log(log_content, log_file)


# Global logger instance
_logger_instance: Optional[LLMPromptLogger] = None


def get_llm_logger(log_dir: str = "logs") -> LLMPromptLogger:
    """Get or create the global LLMPromptLogger instance."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = LLMPromptLogger(log_dir)
    return _logger_instance


__all__ = ["LLMPromptLogger", "get_llm_logger"]
