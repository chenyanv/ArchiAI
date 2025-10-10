from __future__ import annotations

from typing import Iterable, List, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session

from structural_scaffolding.database import (
    DirectorySummaryRecord,
    ProfileRecord,
    create_session,
)

from .models import DirectoryInsight, ProfileInsight
from .state import WorkflowAgentConfig

_PROFILE_QUERY_LIMIT = 120


class DirectoryInsightTool:
    """Traverse directory summary records and surface the most relevant entries."""

    def __init__(self, *, max_directories: int = 6) -> None:
        self._max_directories = max_directories

    def __call__(
        self,
        config: WorkflowAgentConfig,
        hints: Sequence[str],
    ) -> List[DirectoryInsight]:
        session = create_session(config.database_url)
        try:
            query = session.query(DirectorySummaryRecord)
            if config.root_path:
                query = query.filter(DirectorySummaryRecord.root_path == config.root_path)
            query = query.order_by(DirectorySummaryRecord.directory_path)
            records = query.all()
        finally:
            session.close()

        if not records:
            return []

        normalised_hints = [_normalise_hint(hint) for hint in hints if hint]
        filtered: List[DirectorySummaryRecord] = [
            record for record in records if _matches_directory(record, normalised_hints)
        ]
        if not filtered:
            filtered = records

        if self._max_directories > 0:
            filtered = filtered[: self._max_directories]

        return [_build_directory_insight(record) for record in filtered]


class ProfileInsightTool:
    """Select representative profiles within the highlighted directories."""

    def __init__(self, *, max_profiles_per_directory: int = 4) -> None:
        self._max_profiles = max_profiles_per_directory

    def __call__(
        self,
        config: WorkflowAgentConfig,
        directories: Sequence[DirectoryInsight],
    ) -> List[ProfileInsight]:
        if not directories:
            return []

        session = create_session(config.database_url)
        insights: List[ProfileInsight] = []
        try:
            for directory in directories:
                records = self._load_profiles(session, config, directory)
                scored = []
                for record in records:
                    insight = _build_profile_insight(record, directory.directory_path)
                    if insight is None:
                        continue
                    score = _score_profile(record, insight)
                    scored.append((score, insight, record.start_line or 0, insight.file_path))

                scored.sort(key=lambda item: (-item[0], item[2], item[3]))
                limited = [item[1] for item in scored[: self._max_profiles]]
                insights.extend(limited)
        finally:
            session.close()

        return insights

    def _load_profiles(
        self,
        session: Session,
        config: WorkflowAgentConfig,
        directory: DirectoryInsight,
    ) -> List[ProfileRecord]:
        query = session.query(ProfileRecord)
        root_path = config.root_path or directory.root_path
        if root_path:
            query = query.filter(ProfileRecord.root_path == root_path)

        directory_path = _normalise_directory_path(directory.directory_path)
        if directory_path not in {"", "."}:
            like_pattern = f"{directory_path}/%"
            query = query.filter(
                or_(
                    ProfileRecord.file_path == directory_path,
                    ProfileRecord.file_path.like(like_pattern),
                )
            )

        query = query.order_by(ProfileRecord.file_path, ProfileRecord.start_line).limit(_PROFILE_QUERY_LIMIT)
        return query.all()


def _build_directory_insight(record: DirectorySummaryRecord) -> DirectoryInsight:
    summary_payload = record.summary if isinstance(record.summary, dict) else {}
    overview = _as_string(summary_payload.get("overview"))
    key_capabilities = _string_list(summary_payload.get("key_capabilities"))
    return DirectoryInsight(
        root_path=record.root_path or "",
        directory_path=_normalise_directory_path(record.directory_path or ""),
        summary=summary_payload,
        file_count=record.file_count or 0,
        source_files=[str(item) for item in (record.source_files or [])],
        overview=overview,
        key_capabilities=key_capabilities,
    )


def _build_profile_insight(record: ProfileRecord, directory_path: str) -> ProfileInsight | None:
    summaries = record.summaries if isinstance(record.summaries, dict) else {}
    level_1 = summaries.get("level_1") if isinstance(summaries.get("level_1"), dict) else {}

    summary_block = level_1.get("summary") if isinstance(level_1.get("summary"), dict) else {}
    workflow_hints = level_1.get("workflow_hints") if isinstance(level_1.get("workflow_hints"), dict) else {}

    core_identity = _as_string(summary_block.get("core_identity"))
    business_intent = _as_string(summary_block.get("business_intent"))
    workflow_role = _as_string(workflow_hints.get("role"))

    docstring = _as_string(record.docstring)

    if not any([core_identity, business_intent, workflow_role, docstring]):
        return None

    return ProfileInsight(
        profile_id=record.id,
        name=_display_name(record),
        kind=record.kind,
        file_path=_normalise_directory_path(record.file_path or ""),
        directory_path=_normalise_directory_path(directory_path),
        summary=summary_block,
        workflow_hints=workflow_hints,
        docstring=docstring,
        core_identity=core_identity,
        business_intent=business_intent,
        workflow_role=workflow_role,
    )


def _score_profile(record: ProfileRecord, insight: ProfileInsight) -> float:
    score = 0.0
    if insight.workflow_role:
        score += 4.0
    if insight.core_identity:
        score += 3.0
    if insight.business_intent:
        score += 2.0
    if insight.docstring:
        score += 1.0
    if record.kind in {"class", "function"}:
        score += 1.0
    elif record.kind == "method":
        score += 0.5

    call_count = len(record.calls or [])
    score += min(call_count, 5) * 0.2
    return score


def _matches_directory(record: DirectorySummaryRecord, hints: Sequence[str]) -> bool:
    if not hints:
        return True

    directory_path = _normalise_hint(record.directory_path)
    summary_text = _summary_text(record.summary)

    for hint in hints:
        if not hint:
            continue
        if hint == directory_path:
            return True
        if hint in directory_path:
            return True
        if hint in summary_text:
            return True
    return False


def _normalise_hint(value: str) -> str:
    cleaned = (value or "").strip().replace("\\", "/").lower()
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _normalise_directory_path(value: str) -> str:
    cleaned = (value or "").replace("\\", "/").strip()
    if not cleaned:
        return "."
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    while "//" in cleaned:
        cleaned = cleaned.replace("//", "/")
    if cleaned == "":
        return "."
    return cleaned


def _summary_text(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    parts: List[str] = []

    def _collect(value: object) -> None:
        if value is None:
            return
        if isinstance(value, str):
            parts.append(value.lower())
        elif isinstance(value, dict):
            for item in value.values():
                _collect(item)
        elif isinstance(value, Iterable):
            for item in value:
                _collect(item)

    _collect(payload)
    return " ".join(parts)


def _string_list(value: object) -> List[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        return []
    result: List[str] = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                result.append(stripped)
    return result


def _as_string(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    text = str(value).strip()
    return text or None


def _display_name(record: ProfileRecord) -> str:
    if record.class_name and record.function_name:
        return f"{record.class_name}.{record.function_name}"
    if record.function_name:
        return record.function_name
    if record.class_name:
        return record.class_name
    return record.file_path or record.id


__all__ = [
    "DirectoryInsightTool",
    "ProfileInsightTool",
]
