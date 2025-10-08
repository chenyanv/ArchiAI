from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from celery.utils.log import get_task_logger

from structural_scaffolding.database import create_session
from structural_scaffolding.utils import db as db_utils
from structural_scaffolding.utils.tracer import trace_workflow

from .celery_app import celery_app
from .llm import (
    LLMConfigurationError,
    LLMPermanentError,
    LLMRetryableError,
    request_workflow_completion,
)

logger = logging.getLogger(__name__)
task_logger = get_task_logger(__name__)

PROMPT_TEMPLATE = """You are a principal software architect analysing an end-to-end business workflow.

You are given the entry-point source code along with summaries of the critical steps in its call chain.

Return one valid JSON object that follows this schema exactly:
{{
  "workflow_name": "<string>",
  "steps": [
    {{
      "step_number": <integer starting at 1 and increasing by 1>,
      "action": "<string describing what happens>",
      "component": "<string naming the component/module>",
      "details": "<string with relevant parameters, conditions, or side effects>"
    }}
  ]
}}

Rules:
- Output ONLY the JSON object, no markdown fences or additional commentary.
- Populate every required field even if you must infer reasonable details from the context.
- Ensure step numbers are sequential starting at 1.

[Context Information]
{context}
"""
_WORKFLOW_MAX_RETRIES = int(os.getenv("WORKFLOW_SYNTHESIS_MAX_RETRIES", "3"))


def synthesize_workflow(entry_point_id: str, *, database_url: str | None = None) -> Optional[Dict]:
    """Generate and persist a workflow description for the provided entry point."""

    session = create_session(database_url)
    try:
        call_chain = trace_workflow(entry_point_id, session=session)
        context = _build_llm_context(entry_point_id, call_chain, session=session)
        prompt = PROMPT_TEMPLATE.format(context=context)

        try:
            response_text = request_workflow_completion(prompt, expect_json=True)
        except LLMRetryableError:
            task_logger.warning(
                "Transient LLM failure while synthesizing workflow",
                extra={"entry_point_id": entry_point_id},
            )
            raise
        except (LLMConfigurationError, LLMPermanentError):
            task_logger.exception(
                "Permanent LLM failure while synthesizing workflow",
                extra={"entry_point_id": entry_point_id},
            )
            return None
        except Exception:
            task_logger.exception(
                "Unexpected failure while invoking LLM for workflow synthesis",
                extra={"entry_point_id": entry_point_id},
            )
            raise

        try:
            parsed_payload = json.loads(_extract_json_block(response_text))
        except json.JSONDecodeError:
            task_logger.warning(
                "Received non-JSON response from LLM",
                extra={"entry_point_id": entry_point_id},
            )
            return None

        workflow_data = _normalise_workflow_json(parsed_payload)
        if workflow_data is None or not _validate_workflow_json(workflow_data):
            task_logger.warning("Invalid workflow structure received", extra={"entry_point_id": entry_point_id})
            return None

        db_utils.save_workflow(entry_point_id, workflow_data, session=session)
        return workflow_data
    except LLMRetryableError:
        session.rollback()
        logger.warning("Workflow synthesis will be retried for %s", entry_point_id)
        raise
    except Exception:
        session.rollback()
        logger.exception("Workflow synthesis failed for %s", entry_point_id)
        return None
    finally:
        session.close()


@celery_app.task(
    bind=True,
    name="structural_scaffolding.tasks.synthesize_workflow",
    autoretry_for=(LLMRetryableError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": _WORKFLOW_MAX_RETRIES},
)
def synthesize_workflow_task(self, entry_point_id: str, *, database_url: str | None = None) -> Dict | None:
    """Celery task wrapper for workflow synthesis."""

    result = synthesize_workflow(entry_point_id, database_url=database_url)
    if result is None:
        task_logger.warning("Workflow synthesis returned no result", extra={"entry_point_id": entry_point_id})
        return None
    task_logger.info("Workflow stored", extra={"entry_point_id": entry_point_id})
    return result


def _build_llm_context(entry_point_id: str, call_chain: List[str], *, session) -> str:
    context_parts: List[str] = []
    all_profile_ids = _unique_sequence([entry_point_id, *call_chain])
    profiles_data = db_utils.get_full_profiles(all_profile_ids, session=session)

    entry_profile = profiles_data.get(entry_point_id)
    if entry_profile:
        context_parts.append("### WORKFLOW ENTRY POINT: SOURCE CODE\n")
        context_parts.append(f"File: {entry_profile.get('file_path', '')}\n")
        context_parts.append(f"Name: {entry_profile.get('name', entry_point_id)}\n")
        source_code = entry_profile.get("source_code") or ""
        context_parts.append("```python\n")
        context_parts.append(source_code)
        context_parts.append("\n```\n")

    context_parts.append("\n### KEY STEPS IN THE CALL CHAIN: SUMMARIES\n")

    step_counter = 1
    for profile_id in call_chain:
        if profile_id == entry_point_id:
            continue
        profile = profiles_data.get(profile_id)
        if not profile:
            continue

        context_parts.append(f"--- Step {step_counter}: {profile.get('name', profile_id)} ---\n")
        summary_info = {
            "summary": _select_summary(profile.get("summary")),
            "workflow_hints": profile.get("workflow_hints"),
        }
        context_parts.append(json.dumps(summary_info, indent=2))
        context_parts.append("\n")

        step_counter += 1

    return "".join(context_parts).strip()


def _select_summary(summary_payload):
    if isinstance(summary_payload, dict):
        level_1 = summary_payload.get("level_1")
        if isinstance(level_1, dict):
            narrative = level_1.get("summary") or level_1.get("text")
            if narrative:
                return narrative
        if "summary" in summary_payload:
            return summary_payload["summary"]
    return summary_payload


def _normalise_workflow_json(payload: Any) -> Optional[Dict]:
    if _validate_workflow_json(payload):
        return payload

    if isinstance(payload, dict):
        entry = payload.get("workflow_entry_point") or {}
        steps = payload.get("key_steps")

        if isinstance(steps, list) and steps:
            workflow_name = (
                payload.get("workflow_name")
                or entry.get("name")
                or entry.get("class")
                or entry.get("file")
                or "Workflow"
            )
            component_fallback = entry.get("class") or entry.get("file") or "unknown_component"

            normalised_steps: List[Dict[str, Any]] = []
            for idx, step in enumerate(steps, start=1):
                if isinstance(step, dict):
                    action = step.get("action") or step.get("step") or f"Step {idx}"
                    component = step.get("component") or component_fallback
                    details = step.get("details") or step.get("description") or ""
                else:
                    action = str(step)
                    component = component_fallback
                    details = ""

                normalised_steps.append(
                    {
                        "step_number": idx,
                        "action": str(action).strip() or f"Step {idx}",
                        "component": str(component).strip() or "unknown_component",
                        "details": str(details).strip() or "Details not provided.",
                    }
                )

            normalised = {
                "workflow_name": str(workflow_name).strip() or "Workflow",
                "steps": normalised_steps,
            }
            if _validate_workflow_json(normalised):
                return normalised

    return payload if _validate_workflow_json(payload) else None


def _extract_json_block(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # drop opening fence
        if lines:
            lines = lines[1:]
        # drop closing fence
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
        return text[first_brace : last_brace + 1]
    return text


def _validate_workflow_json(payload: Dict) -> bool:
    if not isinstance(payload, dict):
        return False

    workflow_name = payload.get("workflow_name")
    if not isinstance(workflow_name, str) or not workflow_name.strip():
        return False

    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        return False

    required_fields = {"step_number", "action", "component", "details"}
    for step in steps:
        if not isinstance(step, dict):
            return False
        if not required_fields.issubset(step.keys()):
            return False

    return True


def _unique_sequence(items: List[str]) -> List[str]:
    seen = dict.fromkeys(item for item in items if item)
    return list(seen)


__all__ = ["synthesize_workflow", "synthesize_workflow_task"]
