from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from celery.utils.log import get_task_logger
from sqlalchemy.exc import SQLAlchemyError

from structural_scaffolding.database import (
    ProfileRecord,
    WorkflowEntryPointRecord,
    create_session,
)
from structural_scaffolding.models import SummaryLevel

from .celery_app import celery_app
from .context import build_l1_context
from .data_access import load_profile
from .llm import (
    LLMConfigurationError,
    LLMPermanentError,
    LLMRetryableError,
    request_l1_summary,
)

logger = get_task_logger(__name__)
_MAX_LLM_RETRIES = int(os.getenv("L1_SUMMARY_MAX_RETRIES", "5"))


@celery_app.task(
    bind=True,
    name="structural_scaffolding.tasks.generate_l1_summary",
    autoretry_for=(LLMRetryableError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": _MAX_LLM_RETRIES},
)
def generate_l1_summary(self, profile_id: str, *, database_url: str | None = None) -> Dict[str, Any]:
    session = create_session(database_url)
    try:
        record = load_profile(session, profile_id)
        if record is None:
            logger.warning("Profile %s not found; skipping", profile_id)
            return {"profile_id": profile_id, "status": "missing"}

        context = build_l1_context(session, record)
        summary_payload = request_l1_summary(context)
        _persist_summary(session, record, summary_payload)

        logger.info("Stored L1 summary", extra={"profile_id": profile_id})
        return {"profile_id": profile_id, "status": "completed"}

    except LLMConfigurationError as exc:
        logger.error("LLM configuration error: %s", exc)
        raise
    except LLMPermanentError as exc:
        logger.error("LLM permanent error for %s: %s", profile_id, exc)
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        logger.exception("Database error while processing %s", profile_id)
        raise
    except Exception as exc:  # pragma: no cover - safety net
        session.rollback()
        logger.exception("Unexpected failure for %s", profile_id)
        raise
    finally:
        session.close()


def _persist_summary(session, record: ProfileRecord, summary_payload: Dict[str, Any]) -> None:
    summaries = dict(record.summaries or {})
    summaries["level_1"] = summary_payload

    record.summaries = summaries
    record.summary_level = SummaryLevel.LEVEL_1.value

    payload = dict(record.data or {})
    payload["summaries"] = summaries
    payload["summary_level"] = SummaryLevel.LEVEL_1.value
    entry_point_payload = summary_payload.get("entry_point")
    if entry_point_payload is not None:
        payload["entry_point"] = entry_point_payload
    else:
        payload.pop("entry_point", None)
    record.data = payload

    _persist_entry_point(session, record, entry_point_payload)

    session.add(record)
    session.commit()


def _persist_entry_point(
    session,
    component: ProfileRecord,
    entry_payload: Dict[str, Any] | None,
) -> None:
    candidate_ids: List[str] = []
    for value in component.children or []:
        if isinstance(value, str):
            candidate_ids.append(value)
    candidate_ids.append(component.id)

    existing_records: List[WorkflowEntryPointRecord] = []
    if candidate_ids:
        existing_records = (
            session.query(WorkflowEntryPointRecord)
            .filter(WorkflowEntryPointRecord.profile_id.in_(candidate_ids))
            .all()
        )

    if not entry_payload or not isinstance(entry_payload, dict):
        for record in existing_records:
            session.delete(record)
        return

    profile_id = entry_payload.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id.strip():
        for record in existing_records:
            session.delete(record)
        return

    profile_id = profile_id.strip()
    entry_record = next((item for item in existing_records if item.profile_id == profile_id), None)

    for record in existing_records:
        if record.profile_id != profile_id:
            session.delete(record)

    confidence_label = _normalise_entry_point_confidence(entry_payload.get("confidence"))
    display_name = entry_payload.get("display_name") or profile_id
    if not isinstance(display_name, str):
        display_name = str(display_name)

    display_name = display_name.strip()
    confidence_label = _adjust_entry_point_confidence(display_name, confidence_label)

    context_payload = {
        "source_component": component.id,
        "reasons": entry_payload.get("reasons"),
    }

    if entry_record is None:
        entry_record = WorkflowEntryPointRecord(
            profile_id=profile_id,
            entry_point_type="L1_SUMMARY",
            name=display_name.strip() or profile_id,
            confidence=confidence_label,
            context=context_payload,
        )
    else:
        entry_record.entry_point_type = "L1_SUMMARY"
        entry_record.name = display_name.strip() or profile_id
        entry_record.confidence = confidence_label
        entry_record.context = context_payload

    session.add(entry_record)


def _normalise_entry_point_confidence(value: Any) -> str:
    if isinstance(value, str):
        label = value.strip().upper()
    elif value is None:
        label = ""
    else:
        label = str(value).strip().upper()

    if label in {"HIGH", "MEDIUM", "LOW"}:
        return label
    return "MEDIUM"


def _adjust_entry_point_confidence(display_name: str, confidence: str) -> str:
    if display_name == "__init__":
        return "LOW"
    return confidence


__all__ = ["generate_l1_summary"]
