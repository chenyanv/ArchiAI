from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, Optional

from openai import OpenAI

DEFAULT_MODEL = "gpt-4o"
MODEL_ENV_VAR = "ORCHESTRATION_OPENAI_MODEL"
API_KEY_ENV_PREFERENCE = (
    "ORCHESTRATION_OPENAI_API_KEY",
    "OPENAI_API_KEY",
)


class ChatGPTConfigurationError(RuntimeError):
    """Raised when the ChatGPT client cannot be configured."""


class ChatGPTResponseError(RuntimeError):
    """Raised when ChatGPT returns a response that cannot be processed."""

    def __init__(self, message: str, *, metadata: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.metadata = metadata or {}


def _resolve_api_key() -> str:
    for env_name in API_KEY_ENV_PREFERENCE:
        value = os.getenv(env_name)
        if value:
            return value
    raise ChatGPTConfigurationError(
        "Missing OpenAI API key. Set one of: "
        f"{', '.join(API_KEY_ENV_PREFERENCE)}."
    )


def _resolve_model() -> str:
    return os.getenv(MODEL_ENV_VAR, DEFAULT_MODEL)


@lru_cache(maxsize=1)
def _get_client() -> OpenAI:
    api_key = _resolve_api_key()
    return OpenAI(api_key=api_key)


def invoke_chatgpt(
    prompt: str,
    *,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,  # noqa: ARG001 - kept for call-site compatibility
    max_output_tokens: Optional[int] = None,
) -> str:
    """
    Execute a text-only generation request against ChatGPT.
    """
    client = _get_client()
    request_params: Dict[str, Any] = {
        "model": _resolve_model(),
        "messages": [{"role": "user", "content": prompt}],
    }
    if temperature is not None:
        request_params["temperature"] = temperature
    if top_p is not None:
        request_params["top_p"] = top_p
    if max_output_tokens is not None:
        request_params["max_tokens"] = max_output_tokens

    try:
        completion = client.chat.completions.create(**request_params)
    except Exception as exc:  # pragma: no cover - defensive against SDK variations
        raise ChatGPTResponseError(
            "Failed to invoke ChatGPT.",
            metadata={
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            },
        ) from exc

    choices: list[Any] = getattr(completion, "choices", []) or []
    if not choices:
        raise ChatGPTResponseError(
            "ChatGPT returned no choices.",
            metadata={"response_id": getattr(completion, "id", None)},
        )

    first_choice = choices[0]
    message = getattr(first_choice, "message", None)
    content: Optional[str] = None
    if message and isinstance(getattr(message, "content", None), str):
        content = message.content
    elif hasattr(first_choice, "text") and isinstance(first_choice.text, str):
        content = first_choice.text

    if not content or not content.strip():
        raise ChatGPTResponseError(
            "ChatGPT returned empty content.",
            metadata={
                "finish_reason": getattr(first_choice, "finish_reason", None),
                "response_id": getattr(completion, "id", None),
            },
        )

    return content.strip()
