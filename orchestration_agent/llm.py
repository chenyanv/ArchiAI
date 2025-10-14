from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional

from openai import APIConnectionError, APIError, OpenAI, RateLimitError

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


@lru_cache(maxsize=1)
def _get_openai_client() -> OpenAI:
    api_key = _resolve_api_key(LLMProvider.OPENAI)
    return OpenAI(api_key=api_key)


def _coalesce_openai_response_text(response: Any) -> Optional[str]:
    """
    Extract textual content from an OpenAI Chat Completions payload.
    """
    fragments: list[str] = []
    choices = getattr(response, "choices", None) or []
    for choice in choices:
        message = getattr(choice, "message", None)
        if message:
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                fragments.append(content.strip())
    if fragments:
        return "\n".join(fragments)
    return None

def _coalesce_gemini_response_text(response: Any) -> tuple[str | None, set[str] | None]:
    """
    Extract textual content from a Gemini API payload, handling safety blocks.
    """
    blocked_categories: set[str] = set()

    try:
        text = getattr(response, "text", None)
    except ValueError:
        # This occurs when the response is blocked.
        text = None

    if isinstance(text, str) and text.strip():
        return text.strip(), None

    candidates = getattr(response, "candidates", None) or []
    if not candidates and hasattr(response, "prompt_feedback"):
        feedback = getattr(response, "prompt_feedback")
        block_reason = getattr(feedback, "block_reason", None)
        if block_reason:
            blocked_categories.add(str(block_reason))

    for candidate in candidates:
        safety_ratings = getattr(candidate, "safety_ratings", None) or []
        is_blocked = False
        for rating in safety_ratings:
            if getattr(rating, "blocked", False):
                is_blocked = True
                category = getattr(rating, "category", None)
                blocked_categories.add(str(category) if category else "unspecified")
        if is_blocked:
            continue

        fragments: list[str] = []
        content = getattr(candidate, "content", None)
        if content is None and isinstance(candidate, Mapping):
            content = candidate.get("content")
        parts = getattr(content, "parts", None) if content is not None else None
        if parts is None and isinstance(content, Mapping):
            parts = content.get("parts")
        if parts:
            for part in parts:
                piece = getattr(part, "text", None)
                if piece is None and isinstance(part, Mapping):
                    piece = part.get("text")
                if piece:
                    fragments.append(str(piece))
        
        candidate_text = "".join(fragments).strip()
        if candidate_text:
            return candidate_text, None

    return None, blocked_categories or None


def _summarise_gemini_debug(response: Any) -> Dict[str, Any]:
    """
    Build a lightweight, JSON-serialisable diagnostic payload for Gemini responses that
    lack textual content. Keeps personal data out while surfacing safety and finish info.
    """
    metadata: Dict[str, Any] = {}

    prompt_feedback = getattr(response, "prompt_feedback", None)
    if prompt_feedback is not None:
        block_reason = getattr(prompt_feedback, "block_reason", None)
        if block_reason:
            metadata["prompt_block_reason"] = str(block_reason)
        safety_ratings = getattr(prompt_feedback, "safety_ratings", None) or []
        feedback_safety: List[Dict[str, Any]] = []
        for rating in safety_ratings:
            feedback_safety.append(
                {
                    "category": str(getattr(rating, "category", None)),
                    "probability": getattr(rating, "probability", None),
                    "blocked": getattr(rating, "blocked", None),
                }
            )
        if feedback_safety:
            metadata["prompt_feedback_safety"] = feedback_safety

    candidates = getattr(response, "candidates", None) or []
    candidate_diagnostics: List[Dict[str, Any]] = []
    for index, candidate in enumerate(candidates[:3]):
        finish_reason = getattr(candidate, "finish_reason", None)
        safety_ratings = getattr(candidate, "safety_ratings", None) or []
        candidate_safety: List[Dict[str, Any]] = []
        for rating in safety_ratings:
            candidate_safety.append(
                {
                    "category": str(getattr(rating, "category", None)),
                    "probability": getattr(rating, "probability", None),
                    "blocked": getattr(rating, "blocked", None),
                }
            )

        content = getattr(candidate, "content", None)
        if content is None and isinstance(candidate, Mapping):
            content = candidate.get("content")
        parts = getattr(content, "parts", None) if content is not None else None
        if parts is None and isinstance(content, Mapping):
            parts = content.get("parts")

        part_preview: List[str] = []
        if parts:
            for part in list(parts)[:3]:
                piece = getattr(part, "text", None)
                if piece is None and isinstance(part, Mapping):
                    piece = part.get("text")
                if piece:
                    snippet = str(piece).strip()
                    if len(snippet) > 160:
                        snippet = f"{snippet[:157]}..."
                    part_preview.append(snippet)
                else:
                    part_preview.append(f"<no-text:{type(part).__name__}>")

        candidate_diagnostics.append(
            {
                "index": index,
                "finish_reason": str(finish_reason) if finish_reason is not None else None,
                "part_count": len(parts) if parts is not None else 0,
                "part_preview": part_preview,
                "safety": candidate_safety,
            }
        )

    if candidate_diagnostics:
        metadata["candidate_diagnostics"] = candidate_diagnostics

    try:
        text_attr = getattr(response, "text", None)
    except ValueError:
        text_attr = None
    if isinstance(text_attr, str):
        metadata["raw_text_length"] = len(text_attr.strip())

    return metadata


def _invoke_gemini(
    prompt: str,
    *,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
) -> str:
    api_key = _resolve_api_key(LLMProvider.GEMINI)
    model_name = _resolve_model(LLMProvider.GEMINI)
    try:
        import google.generativeai as genai
        from google.api_core import exceptions as google_exceptions
    except ImportError as exc:
        raise LLMConfigurationError("google-generativeai package is not installed") from exc

    genai.configure(api_key=api_key)
    
    generation_config = {
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        "response_mime_type": "application/json",
    }

    prompt_segments = _segment_prompt_for_gemini(prompt)
    contents = [
        {
            "role": "user",
            "parts": [{"text": segment}],
        }
        for segment in prompt_segments
    ]

    try:
        model_ref = genai.GenerativeModel(model_name, generation_config=generation_config)
        response = model_ref.generate_content(contents)
    except google_exceptions.ResourceExhausted as exc:
        raise LLMResponseError("Gemini quota exhausted or rate limited") from exc
    except google_exceptions.ServiceUnavailable as exc:
        raise LLMResponseError("Gemini service unavailable") from exc
    except google_exceptions.GoogleAPIError as exc:
        raise LLMResponseError(str(exc)) from exc
    except Exception as exc:
        raise LLMResponseError("Unexpected error calling Gemini") from exc

    text, blocked_categories = _coalesce_gemini_response_text(response)
    if text:
        return text

    if blocked_categories:
        categories = ", ".join(sorted(blocked_categories))
        raise LLMResponseError(
            f"Gemini response blocked by safety filters ({categories})",
            metadata=_summarise_gemini_debug(response),
        )

    raise LLMResponseError(
        "Gemini response did not include content",
        metadata=_summarise_gemini_debug(response),
    )


def _segment_prompt_for_gemini(prompt: str, *, max_chunk_chars: int = 3500) -> List[str]:
    """
    Split long prompts into smaller text parts for Gemini to reduce blocking.
    """
    stripped = prompt.strip()
    if not stripped:
        return [prompt]

    segments: List[str] = []
    current: List[str] = []
    current_len = 0

    def flush_current() -> None:
        nonlocal current, current_len
        if current:
            combined = "\n\n".join(current).strip()
            if combined:
                segments.append(combined)
        current = []
        current_len = 0

    for block in stripped.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        block_len = len(block)
        if current_len and current_len + 2 + block_len > max_chunk_chars:
            flush_current()
        if block_len > max_chunk_chars:
            # Hard split oversized block
            for idx in range(0, block_len, max_chunk_chars):
                chunk = block[idx : idx + max_chunk_chars].strip()
                if chunk:
                    segments.append(chunk)
            continue

        current.append(block)
        current_len += (2 if current_len else 0) + block_len

    flush_current()

    return segments or [stripped]


def invoke_llm(
    prompt: str,
    *,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
) -> str:
    """
    Execute a text-only LLM call.
    """
    provider = _resolve_provider()
    if provider is LLMProvider.GEMINI:
        return _invoke_gemini(
            prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

    # Fallback to OpenAI
    client = _get_openai_client()
    request_params: Dict[str, Any] = {
        "model": _resolve_model(LLMProvider.OPENAI),
        "messages": [{"role": "user", "content": prompt}],
    }

    if temperature is not None:
        request_params["temperature"] = temperature
    if top_p is not None:
        request_params["top_p"] = top_p
    if max_output_tokens is not None:
        request_params["max_tokens"] = max_output_tokens

    try:
        response = client.chat.completions.create(**request_params)
    except RateLimitError as exc:
        raise LLMResponseError(
            "OpenAI rate limit or quota exceeded.",
            metadata={"error_type": "RateLimitError"},
        ) from exc
    except APIConnectionError as exc:
        raise LLMResponseError(
            "Failed to reach OpenAI.",
            metadata={"error_type": "APIConnectionError", "error_message": str(exc)},
        ) from exc
    except APIError as exc:
        raise LLMResponseError(
            "OpenAI API error.",
            metadata={
                "error_type": exc.__class__.__name__,
                "status_code": getattr(exc, "status_code", None),
                "error_message": str(exc),
            },
        ) from exc
    except Exception as exc:
        raise LLMResponseError(
            "Unexpected error invoking OpenAI.",
            metadata={"error_type": exc.__class__.__name__, "error_message": str(exc)},
        ) from exc

    text = _coalesce_openai_response_text(response)
    if text:
        return text

    raise LLMResponseError(
        "OpenAI returned empty content.",
        metadata={
            "response_id": getattr(response, "id", None),
            "model": request_params["model"],
        },
    )
