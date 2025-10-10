from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from structural_scaffolding.database import ProfileRecord
from structural_scaffolding.pipeline.data_access import load_profile, load_profiles_by_ids


class ProfileRepository:
    """Lightweight cache over ProfileRecord access."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._cache: Dict[str, ProfileRecord | None] = {}

    def get(self, profile_id: str) -> ProfileRecord | None:
        if profile_id not in self._cache:
            self._cache[profile_id] = load_profile(self._session, profile_id)
        return self._cache[profile_id]

    def get_many(self, profile_ids: Iterable[str]) -> Dict[str, ProfileRecord | None]:
        missing = [profile_id for profile_id in profile_ids if profile_id not in self._cache]
        if missing:
            records = load_profiles_by_ids(self._session, missing)
            for record in records:
                self._cache[record.id] = record
            for item in missing:
                self._cache.setdefault(item, None)

        return {profile_id: self._cache.get(profile_id) for profile_id in profile_ids}


__all__ = ["ProfileRepository"]

