from __future__ import annotations

import os
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, Iterable, List

from celery.utils.log import get_task_logger
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from structural_scaffolding.database import (
    DirectorySummaryRecord,
    ProfileRecord,
    create_session,
)

from .celery_app import celery_app
from .context import build_directory_context
from .llm import (
    LLMConfigurationError,
    LLMPermanentError,
    LLMRetryableError,
    request_directory_summary,
)

logger = get_task_logger(__name__)
_MAX_DIR_RETRIES = int(os.getenv("DIRECTORY_SUMMARY_MAX_RETRIES", "3"))


def list_directories_for_summary(
    *,
    database_url: str | None = None,
    root_path: str | None = None,
) -> Dict[str, List[str]]:
    """Return mapping of root_path -> directories that have file-level summaries."""

    session = create_session(database_url)
    try:
        stmt = select(ProfileRecord).where(ProfileRecord.kind == "file")
        if root_path is not None:
            stmt = stmt.where(ProfileRecord.root_path == root_path)

        directories: dict[str, set[str]] = defaultdict(set)
        for record in session.scalars(stmt):
            summaries = record.summaries if isinstance(record.summaries, dict) else {}
            level_1 = summaries.get("level_1")
            if not isinstance(level_1, dict):
                continue

            directory = _normalise_directory(record.file_path or "")
            directories[record.root_path or ""].add(directory)

        return {root: sorted(paths) for root, paths in directories.items()}
    finally:
        session.close()


def summarize_directory(
    directory_path: str,
    *,
    root_path: str | None = None,
    database_url: str | None = None,
) -> Dict[str, Any] | None:
    """Synchronously generate and persist a directory-level summary."""

    session = create_session(database_url)
    try:
        try:
            context = build_directory_context(session, directory_path, root_path=root_path)
        except ValueError:
            logger.info("Skipping directory %s (no eligible file summaries)", directory_path)
            return None

        summary_payload = request_directory_summary(context)
        record = _persist_directory_summary(session, context.root_path, context.directory_path, summary_payload, context.files)
        session.commit()

        return {
            "root_path": record.root_path,
            "directory_path": record.directory_path,
            "file_count": record.file_count,
        }
    except (LLMConfigurationError, LLMPermanentError):
        session.rollback()
        logger.exception("Permanent LLM failure while summarising directory %s", directory_path)
        raise
    except LLMRetryableError:
        session.rollback()
        logger.warning("Retryable LLM failure while summarising directory %s", directory_path)
        raise
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Database error while summarising directory %s", directory_path)
        raise
    except Exception:
        session.rollback()
        logger.exception("Unexpected failure while summarising directory %s", directory_path)
        raise
    finally:
        session.close()


@celery_app.task(
    bind=True,
    name="structural_scaffolding.tasks.generate_directory_summary",
    autoretry_for=(LLMRetryableError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": _MAX_DIR_RETRIES},
)
def generate_directory_summary(
    self,
    directory_path: str,
    *,
    root_path: str | None = None,
    database_url: str | None = None,
) -> Dict[str, Any] | None:
    """Celery task wrapper for directory summarisation."""

    return summarize_directory(directory_path, root_path=root_path, database_url=database_url)


def dispatch_directory_summary_tasks(
    *,
    database_url: str | None = None,
    root_path: str | None = None,
) -> int:
    """Enqueue directory summary tasks for all eligible directories."""

    directories = list_directories_for_summary(database_url=database_url, root_path=root_path)
    total = 0

    for group_root, paths in directories.items():
        for directory in paths:
            generate_directory_summary.apply_async(
                args=(directory,),
                kwargs={"root_path": group_root, "database_url": database_url},
            )
            total += 1

    return total


def _persist_directory_summary(
    session,
    root_path: str,
    directory_path: str,
    summary_payload: Dict[str, Any],
    files: Iterable,
) -> DirectorySummaryRecord:
    file_list = [getattr(file, "file_path", str(file)) for file in files]

    record = (
        session.query(DirectorySummaryRecord)
        .filter(
            DirectorySummaryRecord.root_path == root_path,
            DirectorySummaryRecord.directory_path == directory_path,
        )
        .first()
    )

    if record is None:
        record = DirectorySummaryRecord(
            root_path=root_path,
            directory_path=directory_path,
        )

    record.summary = summary_payload
    record.file_count = len(file_list)
    record.source_files = file_list

    session.add(record)
    return record


def _normalise_directory(file_path: str) -> str:
    cleaned = file_path.replace("\\", "/")
    if not cleaned:
        return "."
    path = Path(cleaned)
    parent = path.parent.as_posix()
    return parent if parent and parent != "." else "."


__all__ = [
    "dispatch_directory_summary_tasks",
    "generate_directory_summary",
    "list_directories_for_summary",
    "summarize_directory",
]
