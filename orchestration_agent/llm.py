"""LLM provider abstraction using LangChain for unified interface."""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage


class LLMProvider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"


DEFAULT_MODEL_OPENAI = "gpt-4o-mini"
DEFAULT_MODEL_GEMINI = "gemini-2.5-pro"
PROVIDER_ENV_VAR = "ORCHESTRATION_LLM_PROVIDER"
MODEL_ENV_VAR_OPENAI = "ORCHESTRATION_OPENAI_MODEL"
MODEL_ENV_VAR_GEMINI = "ORCHESTRATION_GEMINI_MODEL"

API_KEY_ENV_PREFERENCE_OPENAI = (
    "ORCHESTRATION_OPENAI_API_KEY",
    "OPENAI_API_KEY",
)
API_KEY_ENV_PREFERENCE_GEMINI = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)


class LLMConfigurationError(RuntimeError):
    """Raised when the LLM client cannot be configured."""


class LLMResponseError(RuntimeError):
    """Raised when the LLM response cannot be processed."""

    def __init__(self, message: str, *, metadata: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.metadata = metadata or {}


def _resolve_api_key(provider: LLMProvider) -> str:
    if provider is LLMProvider.GEMINI:
        env_prefs = API_KEY_ENV_PREFERENCE_GEMINI
        provider_name = "Gemini"
    else:
        env_prefs = API_KEY_ENV_PREFERENCE_OPENAI
        provider_name = "OpenAI"

    for env_name in env_prefs:
        value = os.getenv(env_name)
        if value:
            return value
    raise LLMConfigurationError(
        f"Missing {provider_name} API key. Set one of: "
        f"{', '.join(env_prefs)}."
    )


def _resolve_model(provider: LLMProvider) -> str:
    if provider is LLMProvider.GEMINI:
        return os.getenv(MODEL_ENV_VAR_GEMINI, DEFAULT_MODEL_GEMINI)
    return os.getenv(MODEL_ENV_VAR_OPENAI, DEFAULT_MODEL_OPENAI)


def _resolve_provider() -> LLMProvider:
    raw = os.getenv(PROVIDER_ENV_VAR, "").strip().lower()
    if raw in {"openai", "gpt", "gpt-4"}:
        return LLMProvider.OPENAI
    return LLMProvider.GEMINI


@lru_cache(maxsize=2)
def _get_llm(
    provider: LLMProvider,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
) -> BaseChatModel:
    """Create and cache a LangChain chat model for the given provider."""
    api_key = _resolve_api_key(provider)
    model_name = _resolve_model(provider)

    if provider is LLMProvider.GEMINI:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            raise LLMConfigurationError(
                "langchain-google-genai package is not installed"
            ) from exc

        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
    else:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise LLMConfigurationError(
                "langchain-openai package is not installed"
            ) from exc

        kwargs: Dict[str, Any] = {
            "model": model_name,
            "api_key": api_key,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens

        return ChatOpenAI(**kwargs)


def invoke_llm(
    prompt: str,
    *,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
) -> str:
    """
    Execute a text-only LLM call using LangChain's unified interface.

    Args:
        prompt: The prompt text to send to the LLM.
        temperature: Sampling temperature (0.0-1.0).
        top_p: Nucleus sampling parameter (currently only used by OpenAI).
        max_output_tokens: Maximum tokens in the response.

    Returns:
        The LLM's response text.

    Raises:
        LLMConfigurationError: If the LLM client cannot be configured.
        LLMResponseError: If the LLM call fails or returns empty content.
    """
    provider = _resolve_provider()

    try:
        llm = _get_llm(provider, temperature, max_output_tokens)
    except Exception as exc:
        raise LLMConfigurationError(f"Failed to initialize {provider.value} client") from exc

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
    except Exception as exc:
        error_type = exc.__class__.__name__
        error_message = str(exc)

        # Handle common error types
        if "rate" in error_message.lower() or "quota" in error_message.lower():
            raise LLMResponseError(
                f"{provider.value} rate limit or quota exceeded.",
                metadata={"error_type": error_type},
            ) from exc
        if "connection" in error_message.lower() or "unavailable" in error_message.lower():
            raise LLMResponseError(
                f"Failed to reach {provider.value} API.",
                metadata={"error_type": error_type},
            ) from exc
        if "blocked" in error_message.lower() or "safety" in error_message.lower():
            raise LLMResponseError(
                f"{provider.value} response blocked by safety filters.",
                metadata={"error_type": error_type, "error_message": error_message},
            ) from exc

        raise LLMResponseError(
            f"Error invoking {provider.value}: {error_message}",
            metadata={"error_type": error_type},
        ) from exc

    # Extract text from response
    text = getattr(response, "content", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    raise LLMResponseError(
        f"{provider.value} returned empty content.",
        metadata={"response_type": type(response).__name__},
    )
