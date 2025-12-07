"""LLM factory for the component drilldown sub-agent."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from orchestration_agent.llm import LLMConfigurationError, LLMProvider

COMPONENT_PROVIDER_ENV = "COMPONENT_AGENT_LLM_PROVIDER"
COMPONENT_OPENAI_MODEL_ENV = "COMPONENT_AGENT_OPENAI_MODEL"
COMPONENT_GEMINI_MODEL_ENV = "COMPONENT_AGENT_GEMINI_MODEL"
COMPONENT_OPENAI_KEY_ENV = "COMPONENT_AGENT_OPENAI_API_KEY"
COMPONENT_GEMINI_KEY_ENV = "COMPONENT_AGENT_GEMINI_API_KEY"

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_GEMINI_MODEL = "gemini-2.5-pro"


def _resolve_provider() -> LLMProvider:
    raw = os.getenv(COMPONENT_PROVIDER_ENV) or os.getenv("ORCHESTRATION_LLM_PROVIDER")
    if not raw:
        return LLMProvider.GEMINI
    token = raw.strip().lower()
    if token in {"openai", "gpt", "gpt-4"}:
        return LLMProvider.OPENAI
    return LLMProvider.GEMINI


def _resolve_model(provider: LLMProvider) -> str:
    if provider is LLMProvider.OPENAI:
        return (
            os.getenv(COMPONENT_OPENAI_MODEL_ENV)
            or os.getenv("ORCHESTRATION_OPENAI_MODEL")
            or DEFAULT_OPENAI_MODEL
        )
    return (
        os.getenv(COMPONENT_GEMINI_MODEL_ENV)
        or os.getenv("ORCHESTRATION_GEMINI_MODEL")
        or DEFAULT_GEMINI_MODEL
    )


def _resolve_api_key(provider: LLMProvider) -> str:
    if provider is LLMProvider.OPENAI:
        env_chain = (
            COMPONENT_OPENAI_KEY_ENV,
            "ORCHESTRATION_OPENAI_API_KEY",
            "OPENAI_API_KEY",
        )
    else:
        env_chain = (
            COMPONENT_GEMINI_KEY_ENV,
            "ORCHESTRATION_GEMINI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
        )
    for env in env_chain:
        if not env:
            continue
        value = os.getenv(env)
        if value:
            return value
    provider_label = "OpenAI" if provider is LLMProvider.OPENAI else "Gemini"
    raise LLMConfigurationError(
        f"Missing {provider_label} API key. Set one of: {', '.join(env for env in env_chain if env)}."
    )


@lru_cache(maxsize=4)
def build_component_chat_model(*, temperature: float = 0.0) -> BaseChatModel:
    provider = _resolve_provider()
    model_name = _resolve_model(provider)
    api_key = _resolve_api_key(provider)
    if provider is LLMProvider.OPENAI:
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            api_key=api_key,
        )
    return ChatGoogleGenerativeAI(
        model=model_name,
        temperature=temperature,
        google_api_key=api_key,
        # NOTE: Removed response_format because JSON mode disables tool calling
        # The model will use tool calling first, then return JSON in final response
    )


__all__ = ["build_component_chat_model"]
