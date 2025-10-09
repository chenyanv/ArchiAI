from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Sequence

from openai import APITimeoutError, APIError, OpenAI, RateLimitError

from .context import L1SummaryContext
from .prompts import build_l1_messages


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


@dataclass(frozen=True)
class ChatSettings:
    model: str
    temperature: float
    max_tokens: int


@dataclass(frozen=True)
class ProviderSettings:
    openai: ChatSettings
    gemini: ChatSettings


def request_l1_summary(
    context: L1SummaryContext,
    *,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    settings = _l1_settings(model_override=model)
    provider = _resolve_provider("SUMMARY_PROVIDER")
    messages = build_l1_messages(context)
    raw_response = _execute_chat(messages, settings=settings, provider=provider)
    payload = _extract_json_object(raw_response)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise LLMPermanentError(f"L1 summary provider returned non-JSON content: {payload}") from exc
    if not isinstance(data, dict):
        raise LLMPermanentError("L1 summary response must be a JSON object")
    return _normalise_l1_payload(data)


def request_workflow_completion(
    prompt: str,
    *,
    expect_json: bool = False,  # noqa: FBT002 - retained for backwards compatibility
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> str:
    settings = _workflow_settings(model_override=model)
    provider = _resolve_provider("WORKFLOW_PROVIDER", "SUMMARY_PROVIDER")

    system_message = system_prompt if system_prompt is not None else _workflow_system_prompt()
    messages: list[dict[str, str]] = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": prompt})

    return _execute_chat(messages, settings=settings, provider=provider)


def _execute_chat(
    messages: Sequence[dict[str, str]],
    *,
    settings: ProviderSettings,
    provider: SummaryProvider,
) -> str:
    if provider is SummaryProvider.GEMINI:
        return _call_gemini(messages, settings.gemini)
    return _call_openai(messages, settings.openai)


def _call_openai(messages: Sequence[dict[str, str]], settings: ChatSettings) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMConfigurationError("OPENAI_API_KEY environment variable is not set")

    client = OpenAI(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model=settings.model,
            messages=list(messages),
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
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


def _call_gemini(messages: Sequence[dict[str, str]], settings: ChatSettings) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise LLMConfigurationError("GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable is not set")

    try:
        import google.generativeai as genai
        from google.api_core import exceptions as google_exceptions
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise LLMConfigurationError("google-generativeai package is not installed") from exc

    genai.configure(api_key=api_key)
    prompt = _format_for_gemini(messages)

    generation_config = {
        "temperature": settings.temperature,
        "max_output_tokens": settings.max_tokens,
    }

    try:
        model_ref = genai.GenerativeModel(settings.model, generation_config=generation_config)
        response = model_ref.generate_content(prompt)
    except google_exceptions.ResourceExhausted as exc:
        raise LLMRetryableError("Gemini quota exhausted or rate limited") from exc
    except google_exceptions.ServiceUnavailable as exc:
        raise LLMRetryableError("Gemini service unavailable") from exc
    except google_exceptions.GoogleAPIError as exc:
        raise LLMPermanentError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive fallback
        raise LLMRetryableError("Unexpected error calling Gemini") from exc

    text, blocked_categories = _extract_gemini_text(response)
    if text:
        return text
    if blocked_categories:
        categories = ", ".join(sorted(blocked_categories))
        raise LLMPermanentError(f"Gemini response blocked by safety filters ({categories})")

    raise LLMPermanentError("Gemini response did not include content")


def _l1_settings(*, model_override: Optional[str]) -> ProviderSettings:
    openai_settings = ChatSettings(
        model=model_override or os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini"),
        temperature=float(os.getenv("OPENAI_SUMMARY_TEMPERATURE", "0.2")),
        max_tokens=int(os.getenv("OPENAI_SUMMARY_MAX_TOKENS", "600")),
    )
    gemini_settings = ChatSettings(
        model=model_override or os.getenv("GEMINI_SUMMARY_MODEL", "gemini-2.5-flash"),
        temperature=float(os.getenv("GEMINI_SUMMARY_TEMPERATURE", "0.2")),
        max_tokens=int(os.getenv("GEMINI_SUMMARY_MAX_TOKENS", "1024")),
    )
    return ProviderSettings(openai=openai_settings, gemini=gemini_settings)


def _workflow_settings(*, model_override: Optional[str]) -> ProviderSettings:
    openai_settings = ChatSettings(
        model=model_override
        or os.getenv("OPENAI_WORKFLOW_MODEL")
        or os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini"),
        temperature=float(
            os.getenv("OPENAI_WORKFLOW_TEMPERATURE", os.getenv("OPENAI_SUMMARY_TEMPERATURE", "0.2"))
        ),
        max_tokens=int(os.getenv("OPENAI_WORKFLOW_MAX_TOKENS", "1200")),
    )
    gemini_settings = ChatSettings(
        model=model_override
        or os.getenv("GEMINI_WORKFLOW_MODEL")
        or os.getenv("GEMINI_SUMMARY_MODEL", "gemini-2.5-flash"),
        temperature=float(
            os.getenv("GEMINI_WORKFLOW_TEMPERATURE", os.getenv("GEMINI_SUMMARY_TEMPERATURE", "0.2"))
        ),
        max_tokens=int(os.getenv("GEMINI_WORKFLOW_MAX_TOKENS", "2048")),
    )
    return ProviderSettings(openai=openai_settings, gemini=gemini_settings)


def _workflow_system_prompt() -> Optional[str]:
    return os.getenv(
        "WORKFLOW_SYSTEM_PROMPT",
        "You are a principal workflow architect. Craft precise, implementation-aware summaries.",
    )


def _resolve_provider(*env_keys: str) -> SummaryProvider:
    for key in env_keys:
        if not key:
            continue
        raw = os.getenv(key)
        if not raw:
            continue
        normalised = raw.strip().lower()
        if normalised in {"gemini", "google", "gemini-2.5", "gemini_flash"}:
            return SummaryProvider.GEMINI
        if normalised in {"openai", "gpt", "gpt-4o", "gpt4o"}:
            return SummaryProvider.OPENAI
    return SummaryProvider.OPENAI


def _format_for_gemini(messages: Sequence[dict[str, str]]) -> str:
    sections = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if not content:
            continue
        sections.append(f"[{role.upper()}]\n{content}")
    return "\n\n".join(sections)


def _extract_gemini_text(response) -> tuple[str | None, set[str] | None]:
    try:
        text = getattr(response, "text", None)
    except ValueError:
        text = None

    if isinstance(text, str) and text.strip():
        return text.strip(), None

    candidates = getattr(response, "candidates", None) or []
    blocked_categories: set[str] = set()

    for candidate in candidates:
        safety_ratings = getattr(candidate, "safety_ratings", None) or []
        blocked = False
        for rating in safety_ratings:
            if getattr(rating, "blocked", False):
                blocked = True
                category = getattr(rating, "category", None)
                blocked_categories.add(str(category) if category else "unspecified")
        if blocked:
            continue

        fragments: list[str] = []

        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None)
        if parts:
            for part in parts:
                piece = getattr(part, "text", None)
                if piece:
                    fragments.append(piece)

        alt_text = getattr(candidate, "output_text", None)
        if isinstance(alt_text, str) and alt_text:
            fragments.append(alt_text)

        candidate_text = "".join(fragments).strip()
        if candidate_text:
            return candidate_text, None

    if blocked_categories:
        return None, blocked_categories

    return None, None


def _extract_json_object(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _normalise_l1_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}

    workflow_hints = payload.get("workflow_hints")
    if not isinstance(workflow_hints, dict):
        workflow_hints = {}

    entry_point_raw = payload.get("entry_point")
    entry_point: Dict[str, Any] | None
    if isinstance(entry_point_raw, dict):
        profile_id = str(entry_point_raw.get("profile_id") or "").strip()
        if profile_id:
            entry_point = {
                "profile_id": profile_id,
                "display_name": str(entry_point_raw.get("display_name") or "").strip() or profile_id,
                "confidence": _normalise_confidence_label(entry_point_raw.get("confidence")),
                "reasons": str(entry_point_raw.get("reasons") or "").strip(),
            }
        else:
            entry_point = None
    else:
        entry_point = None

    return {
        "summary": summary,
        "workflow_hints": workflow_hints,
        "entry_point": entry_point,
    }


def _normalise_confidence_label(value: Any) -> str:
    label = ""
    if isinstance(value, str):
        label = value.strip().upper()
    elif value is not None:
        label = str(value).strip().upper()

    if label in {"HIGH", "MEDIUM", "LOW"}:
        return label
    return "MEDIUM"


__all__ = [
    "LLMConfigurationError",
    "LLMError",
    "LLMPermanentError",
    "LLMRetryableError",
    "SummaryProvider",
    "request_l1_summary",
    "request_workflow_completion",
]
