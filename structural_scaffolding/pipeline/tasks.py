from __future__ import annotations

import logging
import os
from typing import Any, Dict

from celery.utils.log import get_task_logger
from sqlalchemy.exc import SQLAlchemyError

from structural_scaffolding.database import ProfileRecord, create_session
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
        summary_text = request_l1_summary(context)
        _persist_summary(session, record, summary_text)

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


def _persist_summary(session, record: ProfileRecord, summary_text: str) -> None:
    summaries = dict(record.summaries or {})
    summaries["level_1"] = summary_text

    record.summaries = summaries
    record.summary_level = SummaryLevel.LEVEL_1.value

    payload = dict(record.data or {})
    payload["summaries"] = summaries
    payload["summary_level"] = SummaryLevel.LEVEL_1.value
    record.data = payload

    session.add(record)
    session.commit()


__all__ = ["generate_l1_summary"]
