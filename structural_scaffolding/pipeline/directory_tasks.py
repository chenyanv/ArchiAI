from __future__ import annotations

import os
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, Iterable, List

from celery import group

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
    """Return mapping of root_path -> directories ordered deepest-first."""

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
            for ancestor in _directory_ancestors(directory):
                directories[record.root_path or ""].add(ancestor)

        ordered: dict[str, List[str]] = {}
        for root, paths in directories.items():
            ordered[root] = sorted(
                paths,
                key=lambda item: (-_directory_level(item), item),
            )
        return ordered
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
            logger.info("Skipping directory %s (no eligible context)", directory_path)
            return None

        summary_payload = request_directory_summary(context)
        record = _persist_directory_summary(
            session,
            context.root_path,
            context.directory_path,
            summary_payload,
            context.files,
            context.child_directories,
        )
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
        depth_buckets: dict[int, list[str]] = defaultdict(list)
        for directory in paths:
            depth_buckets[_directory_level(directory)].append(directory)

        signature = None
        for depth in sorted(depth_buckets.keys(), reverse=True):
            depth_paths = depth_buckets[depth]
            if not depth_paths:
                continue
            group_tasks = [
                generate_directory_summary.s(
                    directory,
                    root_path=group_root,
                    database_url=database_url,
                )
                for directory in depth_paths
            ]
            depth_group = group(group_tasks)
            signature = depth_group if signature is None else signature | depth_group
            total += len(depth_paths)

        if signature is not None:
            signature.apply_async()

    return total


def _persist_directory_summary(
    session,
    root_path: str,
    directory_path: str,
    summary_payload: Dict[str, Any],
    files: Iterable,
    child_directories: Iterable,
) -> DirectorySummaryRecord:
    aggregated_files: set[str] = set()

    for file in files:
        path = getattr(file, "file_path", None)
        if isinstance(path, str) and path:
            aggregated_files.add(path)
        elif isinstance(file, str) and file:
            aggregated_files.add(file)

    for child in child_directories:
        source_files = getattr(child, "source_files", None)
        if not source_files:
            continue
        for child_path in source_files:
            if isinstance(child_path, str) and child_path:
                aggregated_files.add(child_path)

    file_list = sorted(aggregated_files)

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


def _directory_level(directory_path: str) -> int:
    if not directory_path or directory_path in {".", "./"}:
        return 0
    return len([segment for segment in directory_path.strip("/").split("/") if segment and segment != "."])


def _directory_ancestors(directory_path: str) -> List[str]:
    normalised = directory_path.strip() or "."
    if normalised in {".", "./"}:
        return ["."]

    segments = [segment for segment in normalised.strip("/").split("/") if segment and segment != "."]
    ancestors: List[str] = []
    for idx in range(len(segments), 0, -1):
        ancestor = "/".join(segments[:idx])
        ancestors.append(ancestor)
    ancestors.append(".")
    return ancestors


__all__ = [
    "dispatch_directory_summary_tasks",
    "generate_directory_summary",
    "list_directories_for_summary",
    "summarize_directory",
]
