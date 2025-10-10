from __future__ import annotations

from typing import Iterable, List, Sequence

from workflow_tracing.models import DirectoryInsight, ProfileInsight
from workflow_tracing.tools import DirectoryInsightTool, ProfileInsightTool

from .models import TraceSeed
from .state import TopDownAgentConfig


class RepositoryContextLoader:
    """Helper that wraps the existing directory/profile insight tools."""

    def __init__(self, config: TopDownAgentConfig) -> None:
        self._directory_tool = DirectoryInsightTool(max_directories=config.max_directories)
        self._profile_tool = ProfileInsightTool(max_profiles_per_directory=config.profiles_per_directory)

    def load(
        self,
        config: TopDownAgentConfig,
        hints: Sequence[str],
    ) -> tuple[List[DirectoryInsight], List[ProfileInsight]]:
        directories = self._directory_tool(config, hints)
        profiles = self._profile_tool(config, directories)
        return directories, profiles


def build_directory_seeds(directories: Iterable[DirectoryInsight]) -> List[TraceSeed]:
    seeds: List[TraceSeed] = []
    for directory in directories:
        token = directory.directory_path or "."
        label = directory.directory_path or directory.root_path or "."
        aliases = {
            token,
            label,
            directory.root_path or "",
            _basename(token),
        }
        description = directory.overview or "Directory overview not captured."
        summary_lines: List[str] = []
        if directory.overview:
            summary_lines.append(directory.overview)
        if directory.key_capabilities:
            summary_lines.append("Capabilities: " + ", ".join(directory.key_capabilities[:6]))

        seeds.append(
            TraceSeed(
                token=token,
                kind="directory",
                label=label,
                description=description,
                directory_path=token,
                summary="\n".join(summary_lines) if summary_lines else None,
                aliases=[alias for alias in aliases if alias],
                metadata={
                    "root_path": directory.root_path or "",
                    "source_files": ", ".join(directory.source_files[:5]),
                },
            )
        )
    return seeds


def build_profile_seeds(profiles: Iterable[ProfileInsight]) -> List[TraceSeed]:
    seeds: List[TraceSeed] = []
    for profile in profiles:
        token = profile.profile_id
        label = profile.name
        aliases = {
            token,
            label,
            profile.file_path,
            _basename(profile.file_path),
            profile.directory_path,
        }
        description = profile.core_identity or profile.business_intent or profile.workflow_role
        summary_parts: List[str] = []
        if profile.business_intent:
            summary_parts.append(f"Intent: {profile.business_intent}")
        if profile.workflow_role:
            summary_parts.append(f"Role: {profile.workflow_role}")
        if profile.docstring:
            summary_parts.append(f"Docstring: {profile.docstring[:240]}".rstrip())

        seeds.append(
            TraceSeed(
                token=token,
                kind="profile",
                label=label,
                description=description,
                profile_id=profile.profile_id,
                file_path=profile.file_path,
                directory_path=profile.directory_path,
                summary="\n".join(summary_parts) if summary_parts else None,
                aliases=[alias for alias in aliases if alias],
                metadata={
                    "kind": profile.kind,
                },
            )
        )
    return seeds


def match_directories(query: str, directories: Sequence[DirectoryInsight]) -> List[DirectoryInsight]:
    words = _keywords(query)
    if not words:
        return []

    matches: List[DirectoryInsight] = []
    for directory in directories:
        haystack = " ".join(
            filter(
                None,
                [
                    directory.directory_path,
                    directory.overview,
                    " ".join(directory.key_capabilities or []),
                ],
            )
        ).lower()
        if all(word in haystack for word in words):
            matches.append(directory)
    return matches


def match_profiles(query: str, profiles: Sequence[ProfileInsight]) -> List[ProfileInsight]:
    words = _keywords(query)
    if not words:
        return []

    matches: List[ProfileInsight] = []
    for profile in profiles:
        haystack = " ".join(
            filter(
                None,
                [
                    profile.name,
                    profile.file_path,
                    profile.directory_path,
                    profile.business_intent,
                    profile.workflow_role,
                    profile.core_identity,
                    profile.docstring,
                ],
            )
        ).lower()
        if all(word in haystack for word in words):
            matches.append(profile)
    return matches


def _basename(value: str | None) -> str:
    if not value:
        return ""
    cleaned = value.replace("\\", "/").rstrip("/")
    if "/" not in cleaned:
        return cleaned
    return cleaned.split("/")[-1]


def _keywords(value: str) -> List[str]:
    return [token for token in value.lower().replace("-", " ").split() if token]


__all__ = [
    "RepositoryContextLoader",
    "build_directory_seeds",
    "build_profile_seeds",
    "match_directories",
    "match_profiles",
]

