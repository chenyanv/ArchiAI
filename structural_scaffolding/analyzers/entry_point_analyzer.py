from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List, Optional, Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from structural_scaffolding.database import (
    ProfileRecord,
    WorkflowEntryPointRecord,
    create_session,
    resolve_database_url,
)

logger = logging.getLogger(__name__)

class ConfidenceLevel(str, Enum):
    # TODO: 对于这个评级，待优化
    MEDIUM = "MEDIUM"

    @property
    def sort_order(self) -> int:
        return 0


class EntryPointType(str, Enum):
    LLM_SUGGESTED = "LLM_SUGGESTED"


@dataclass(slots=True)
class ProfileSnapshot:
    id: str
    file_path: str
    summaries: dict
    data: dict

    @property
    def workflow_hints(self) -> Optional[dict]:
        def _coerce_mapping(value: object) -> Optional[dict]:
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
            return None

        def _extract(container: dict | None) -> Optional[dict]:
            if not isinstance(container, dict):
                return None

            direct = _coerce_mapping(container.get("workflow_hints"))
            if isinstance(direct, dict):
                return direct

            level_1 = _coerce_mapping(container.get("level_1"))
            if isinstance(level_1, dict):
                nested = _coerce_mapping(level_1.get("workflow_hints"))
                if isinstance(nested, dict):
                    return nested
            return None

        return _extract(self.summaries) or _extract(self.data)


@dataclass(slots=True)
class EntryPointCandidate:
    profile_id: str
    entry_point_type: EntryPointType
    name: str
    confidence: ConfidenceLevel
    context: dict


class WorkflowHintDetector:
    def detect(self, profile: ProfileSnapshot) -> Sequence[EntryPointCandidate]:
        hints = profile.workflow_hints
        if not isinstance(hints, dict):
            return []
        role = hints.get("role")
        if role != "ENTRY_POINT":
            return []
        name = hints.get("potential_workflow_name") or profile.file_path
        return [
            EntryPointCandidate(
                profile_id=profile.id,
                entry_point_type=EntryPointType.LLM_SUGGESTED,
                name=f"AI Suggestion: {name}",
                confidence=ConfidenceLevel.MEDIUM,
                context=hints,
            )
        ]


class EntryPointAnalyzer:
    def __init__(self, session: Session, detectors: Optional[Iterable[object]] = None):
        self.session = session
        self.detectors = list(detectors) if detectors else [WorkflowHintDetector()]

    def run(self) -> List[EntryPointCandidate]:
        profiles = self._load_profiles()
        candidates = self._collect_candidates(profiles)
        persisted = self._persist_candidates(candidates)
        logger.info("Persisted %s workflow entry points", persisted)
        return candidates

    def _load_profiles(self) -> List[ProfileSnapshot]:
        records: List[ProfileSnapshot] = []
        for record in (
            self.session.query(ProfileRecord)
            .filter(ProfileRecord.kind.in_(("function", "method", "class")))
            .filter(ProfileRecord.summaries.has_key("level_1"))  # type: ignore[attr-defined]
            .all()
        ):
            records.append(
                ProfileSnapshot(
                    id=record.id,
                    file_path=record.file_path,
                    summaries=record.summaries or {},
                    data=record.data or {},
                )
            )
        return records

    def _collect_candidates(self, profiles: Iterable[ProfileSnapshot]) -> List[EntryPointCandidate]:
        candidates: List[EntryPointCandidate] = []
        for profile in profiles:
            for detector in self.detectors:
                candidates.extend(detector.detect(profile))
        return candidates

    def _persist_candidates(self, candidates: Iterable[EntryPointCandidate]) -> int:
        if not candidates:
            return 0
        payloads: List[dict] = [
            {
                "profile_id": candidate.profile_id,
                "entry_point_type": candidate.entry_point_type.value,
                "name": candidate.name,
                "confidence": candidate.confidence.value,
                "context": candidate.context or {},
            }
            for candidate in candidates
        ]
        insert_stmt = insert(WorkflowEntryPointRecord)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[WorkflowEntryPointRecord.profile_id],
            set_={
                "entry_point_type": insert_stmt.excluded.entry_point_type,
                "name": insert_stmt.excluded.name,
                "confidence": insert_stmt.excluded.confidence,
                "context": insert_stmt.excluded.context,
            },
        )
        try:
            self.session.execute(upsert_stmt, payloads)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return len(payloads)


def analyze_and_find_entry_points(database_url: Optional[str] = None) -> List[EntryPointCandidate]:
    session = create_session(database_url)
    try:
        analyzer = EntryPointAnalyzer(session)
        return analyzer.run()
    finally:
        session.close()


def main() -> None:
    analyze_and_find_entry_points(resolve_database_url(None))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
