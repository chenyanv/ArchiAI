"""Token usage tracking for LLM calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from langchain_core.messages import BaseMessage


@dataclass
class TokenUsage:
    """Tracks token usage for a single LLM call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""


@dataclass
class TokenTracker:
    """Simple tracker that extracts token usage from message metadata."""

    calls: List[TokenUsage] = field(default_factory=list)
    _checkpoint: int = 0  # Index marking start of current request

    @property
    def total_prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def total_completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return sum(c.total_tokens for c in self.calls)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def track_messages(self, messages: Sequence[BaseMessage]) -> None:
        """Extract token usage from messages with usage_metadata."""
        for msg in messages:
            if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                meta = msg.usage_metadata
                # Handle both dict and object styles
                if isinstance(meta, dict):
                    prompt = meta.get("input_tokens", 0)
                    completion = meta.get("output_tokens", 0)
                    total = meta.get("total_tokens", 0)
                else:
                    prompt = getattr(meta, "input_tokens", 0)
                    completion = getattr(meta, "output_tokens", 0)
                    total = getattr(meta, "total_tokens", 0)

                # Get model name from response_metadata
                model_name = "unknown"
                if hasattr(msg, "response_metadata") and msg.response_metadata:
                    model_name = msg.response_metadata.get("model_name", "unknown")

                usage = TokenUsage(
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    total_tokens=total,
                    model=model_name,
                )
                self.calls.append(usage)

    def reset(self) -> None:
        """Reset tracking data."""
        self.calls.clear()
        self._checkpoint = 0

    def mark_checkpoint(self) -> None:
        """Mark current position as start of a new request."""
        self._checkpoint = len(self.calls)

    def _current_calls(self) -> List[TokenUsage]:
        """Get calls since last checkpoint."""
        return self.calls[self._checkpoint:]

    def summary(self) -> str:
        """Return a formatted summary showing current request + cumulative."""
        current = self._current_calls()
        cur_tokens = sum(c.total_tokens for c in current)
        cur_calls = len(current)

        lines = [
            "┌─────────────────────────────────────────────┐",
            "│            TOKEN USAGE SUMMARY              │",
            "├─────────────────────────────────────────────┤",
            f"│  This Request:   {cur_tokens:>6} tokens ({cur_calls} calls)   │",
            f"│  Session Total:  {self.total_tokens:>6} tokens ({self.call_count} calls)   │",
            "└─────────────────────────────────────────────┘",
        ]
        return "\n".join(lines)

    def detailed_summary(self) -> str:
        """Return detailed per-call breakdown."""
        lines = [self.summary(), "", "Per-call breakdown:"]
        for i, call in enumerate(self.calls, 1):
            lines.append(
                f"  [{i}] {call.model}: {call.prompt_tokens} in / {call.completion_tokens} out = {call.total_tokens} total"
            )
        return "\n".join(lines)


# Global tracker instance for convenience
_global_tracker: Optional[TokenTracker] = None


def get_token_tracker() -> TokenTracker:
    """Get or create the global token tracker."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = TokenTracker()
    return _global_tracker


def reset_token_tracker() -> None:
    """Reset the global token tracker."""
    global _global_tracker
    if _global_tracker:
        _global_tracker.reset()


__all__ = [
    "TokenUsage",
    "TokenTracker",
    "get_token_tracker",
    "reset_token_tracker",
]
