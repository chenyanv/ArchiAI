from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from structural_scaffolding.database import DirectorySummaryRecord, create_session
from structural_scaffolding.pipeline.llm import LLMError, request_workflow_completion

from .prompts import build_business_summary_prompt, build_system_prompt
from .state import AgentConfig, DirectorySummary, TableColumn, TableSnapshot

logger = logging.getLogger(__name__)


class DirectorySummaryTool:
    """Fetch top-level directory summaries from the directory_summaries table."""

    def __init__(self, *, max_directories: int) -> None:
        self._max_directories = max_directories

    def __call__(self, config: AgentConfig) -> List[DirectorySummary]:
        session = create_session(config.database_url)
        try:
            query = session.query(DirectorySummaryRecord)
            if config.root_path is not None:
                query = query.filter(DirectorySummaryRecord.root_path == (config.root_path or ""))

            query = query.order_by(DirectorySummaryRecord.directory_path)
            records = query.all()

            filtered: List[DirectorySummaryRecord] = [
                record
                for record in records
                if _is_top_level_directory(record.directory_path)
            ]

            if self._max_directories > 0:
                filtered = filtered[: self._max_directories]

            results: List[DirectorySummary] = []
            for record in filtered:
                summary_payload = record.summary if isinstance(record.summary, dict) else {}
                results.append(
                    DirectorySummary(
                        root_path=record.root_path or "",
                        directory_path=record.directory_path or ".",
                        summary=summary_payload,
                        file_count=record.file_count or 0,
                        source_files=list(record.source_files or []),
                    )
                )
            return results
        finally:
            session.close()


class TableInspectorTool:
    """Inspect SQLAlchemy models to expose schema and row counts."""

    _TARGET_MODELS = (DirectorySummaryRecord,)

    def __init__(self, *, include_row_counts: bool = True) -> None:
        self._include_row_counts = include_row_counts

    def __call__(self, config: AgentConfig) -> List[TableSnapshot]:
        session = create_session(config.database_url)
        snapshots: List[TableSnapshot] = []
        try:
            for model in self._TARGET_MODELS:
                table = model.__table__
                columns = [
                    TableColumn(
                        name=column.name,
                        type_=str(column.type),
                        nullable=bool(column.nullable),
                    )
                    for column in table.columns
                ]

                row_count: Optional[int] = None
                if self._include_row_counts:
                    try:
                        row_count = session.query(model).count()
                    except SQLAlchemyError as exc:
                        logger.debug("Failed to count rows for %s: %s", table.name, exc)
                        row_count = None

                snapshots.append(
                    TableSnapshot(
                        name=table.name,
                        columns=columns,
                        row_count=row_count,
                    )
                )

            return snapshots
        finally:
            session.close()


class BusinessLogicSynthesizer:
    """Delegate to the LLM (with fallback) to compose the business logic narrative."""

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        self._model = model
        self._system_prompt = system_prompt or build_system_prompt()

    def __call__(
        self,
        directory_summaries: Iterable[DirectorySummary],
        table_snapshots: Iterable[TableSnapshot],
    ) -> str:
        materialised_directories = list(directory_summaries)
        materialised_tables = list(table_snapshots)

        if not materialised_directories:
            return (
                "No top-level directory summaries were available, so the orchestration agent could not "
                "infer high-level business logic. Generate directory summaries first and re-run."
            )

        prompt = build_business_summary_prompt(materialised_directories, materialised_tables)

        try:
            response = request_workflow_completion(
                prompt,
                model=self._model,
                system_prompt=self._system_prompt,
            )
            return response.strip()
        except LLMError as exc:
            logger.warning("LLM orchestration failed; falling back to deterministic summary: %s", exc)
            return _fallback_summary(materialised_directories, materialised_tables, reason=str(exc))


def _fallback_summary(
    directory_summaries: Iterable[DirectorySummary],
    table_snapshots: Iterable[TableSnapshot],
    *,
    reason: str,
) -> str:
    directory_lines: List[str] = []
    for summary in list(directory_summaries)[:5]:
        overview = summary.summary.get("overview", "Overview unavailable.")
        capabilities = summary.summary.get("key_capabilities") or []
        capability_text = ", ".join(capabilities[:3]) if isinstance(capabilities, list) else ""
        if capability_text:
            directory_lines.append(f"{summary.directory_path}: {overview} (capabilities: {capability_text})")
        else:
            directory_lines.append(f"{summary.directory_path}: {overview}")
    directory_block = "\n".join(directory_lines) or "No directory summaries captured."

    return (
        "LLM synthesis could not be completed "
        f"(reason: {reason}).\n\n"
        "Key directories:\n"
        f"{directory_block}\n\n"
        "Next steps: restore LLM access to produce a narrative summary."
    )


def _is_top_level_directory(directory_path: Optional[str]) -> bool:
    if directory_path is None or directory_path.strip() == "":
        return True
    cleaned = directory_path.strip("/").replace("\\", "/")
    if cleaned in {"", "."}:
        return True
    return "/" not in cleaned
