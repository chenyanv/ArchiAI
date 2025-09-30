from __future__ import annotations

import os
from enum import Enum
from typing import Optional

from openai import APITimeoutError, APIError, OpenAI, RateLimitError

from .context import L1SummaryContext
from .prompts import build_l1_messages

_DEFAULT_OPENAI_MODEL = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini")
_DEFAULT_OPENAI_TEMPERATURE = float(os.getenv("OPENAI_SUMMARY_TEMPERATURE", "0.2"))
_DEFAULT_OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_SUMMARY_MAX_TOKENS", "600"))

_DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_SUMMARY_MODEL", "gemini-2.5-flash")
_DEFAULT_GEMINI_TEMPERATURE = float(os.getenv("GEMINI_SUMMARY_TEMPERATURE", "0.2"))
_DEFAULT_GEMINI_MAX_TOKENS = int(os.getenv("GEMINI_SUMMARY_MAX_TOKENS", "1024"))


class SummaryProvider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"


class LLMError(RuntimeError):
    """Base exception for LLM related failures."""


class LLMConfigurationError(LLMError):
    """Raised when configuration is missing or invalid."""


class LLMRetryableError(LLMError):
    """Raised for transient errors that should be retried."""


class LLMPermanentError(LLMError):
    """Raised for errors that retries are unlikely to fix."""


def request_l1_summary(
    context: L1SummaryContext,
    *,
    model: Optional[str] = None,
) -> str:
    provider = _resolve_provider()
    if provider is SummaryProvider.GEMINI:
        return _request_gemini_summary(context, model=model)
    return _request_openai_summary(context, model=model)


def _resolve_provider() -> SummaryProvider:
    raw = os.getenv("SUMMARY_PROVIDER", SummaryProvider.OPENAI.value).strip().lower()
    if raw in {"gemini", "google", "gemini-2.5", "gemini_flash"}:
        return SummaryProvider.GEMINI
    return SummaryProvider.OPENAI


def _request_openai_summary(
    context: L1SummaryContext,
    *,
    model: Optional[str] = None,
) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMConfigurationError("OPENAI_API_KEY environment variable is not set")

    client = OpenAI(api_key=api_key)
    messages = build_l1_messages(context)

    target_model = model or _DEFAULT_OPENAI_MODEL

    try:
        response = client.chat.completions.create(
            model=target_model,
            messages=messages,
            temperature=_DEFAULT_OPENAI_TEMPERATURE,
            max_tokens=_DEFAULT_OPENAI_MAX_TOKENS,
        )
    except (RateLimitError, APITimeoutError) as exc:
        raise LLMRetryableError("Transient OpenAI error") from exc
    except APIError as exc:
        if getattr(exc, "status_code", None) and 500 <= exc.status_code < 600:
            raise LLMRetryableError("OpenAI server error") from exc
        raise LLMPermanentError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive guard for SDK changes
        raise LLMRetryableError("Unexpected error calling OpenAI") from exc

    message = None
    if response.choices:
        message = response.choices[0].message.content if response.choices[0].message else None

    if not message:
        raise LLMPermanentError("OpenAI response did not include content")

    return message.strip()


def _request_gemini_summary(
    context: L1SummaryContext,
    *,
    model: Optional[str] = None,
) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise LLMConfigurationError("GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable is not set")

    try:
        import google.generativeai as genai
        from google.api_core import exceptions as google_exceptions
    except ImportError as exc:  # pragma: no cover - requires optional dependency
        raise LLMConfigurationError("google-generativeai package is not installed") from exc

    genai.configure(api_key=api_key)
    target_model = model or _DEFAULT_GEMINI_MODEL

    messages = build_l1_messages(context)
    prompt = _format_messages_for_gemini(messages)

    generation_config = {
        "temperature": _DEFAULT_GEMINI_TEMPERATURE,
        "max_output_tokens": _DEFAULT_GEMINI_MAX_TOKENS,
    }

    try:
        model_ref = genai.GenerativeModel(target_model, generation_config=generation_config)
        response = model_ref.generate_content(prompt)
    except google_exceptions.ResourceExhausted as exc:
        raise LLMRetryableError("Gemini quota exhausted or rate limited") from exc
    except google_exceptions.ServiceUnavailable as exc:
        raise LLMRetryableError("Gemini service unavailable") from exc
    except google_exceptions.GoogleAPIError as exc:
        raise LLMPermanentError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive fallback
        raise LLMRetryableError("Unexpected error calling Gemini") from exc

    text = getattr(response, "text", None)
    if not text:
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            parts = getattr(candidate, "content", None)
            if parts and getattr(parts, "parts", None):
                pieces = [getattr(part, "text", "") for part in parts.parts]
                text = "".join(piece for piece in pieces if piece)
                if text:
                    break

    if not text:
        raise LLMPermanentError("Gemini response did not include content")

    return text.strip()


def _format_messages_for_gemini(messages: list[dict[str, str]]) -> str:
    sections = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if not content:
            continue
        sections.append(f"[{role.upper()}]\n{content}")
    return "\n\n".join(sections)


__all__ = [
    "LLMConfigurationError",
    "LLMError",
    "LLMPermanentError",
    "LLMRetryableError",
    "SummaryProvider",
    "request_l1_summary",
]
