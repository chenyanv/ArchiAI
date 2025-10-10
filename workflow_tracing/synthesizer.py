from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from structural_scaffolding.pipeline.llm import LLMError, request_workflow_completion

from .models import DirectoryInsight, ProfileInsight, TraceNarrative, TraceStage


@dataclass(frozen=True, slots=True)
class StageDefinition:
    key: str
    name: str
    goal: str
    keywords: tuple[str, ...]


DEFAULT_STAGE_DEFINITIONS: tuple[StageDefinition, ...] = (
    StageDefinition(
        key="ingestion",
        name="Knowledge Ingestion & Parsing",
        goal="Capture raw artefacts and convert them into well-structured knowledge units.",
        keywords=(
            "ingest",
            "ingestion",
            "parser",
            "parsing",
            "chunk",
            "chunker",
            "document",
            "doc",
            "upload",
            "extract",
            "preprocess",
            "etl",
            "deepdoc",
        ),
    ),
    StageDefinition(
        key="retrieval",
        name="Retrieval Augmentation & Indexing",
        goal="Enrich the knowledge base with search-friendly indexes and embeddings.",
        keywords=(
            "vector",
            "embedding",
            "index",
            "search",
            "retrieve",
            "retrieval",
            "rag",
            "graph",
            "knowledge base",
            "graphrag",
            "rank",
            "store",
        ),
    ),
    StageDefinition(
        key="reasoning",
        name="Agent Orchestration & Reasoning",
        goal="Co-ordinate agents, interpret user intent, and synthesise answers.",
        keywords=(
            "agent",
            "reason",
            "reasoning",
            "workflow",
            "plan",
            "planner",
            "api",
            "conversation",
            "orchestrate",
            "agentic",
            "controller",
        ),
    ),
)

SUPPORT_STAGE = StageDefinition(
    key="support",
    name="Supporting Capabilities",
    goal="Cross-cutting utilities that reinforce the primary workflow.",
    keywords=tuple(),
)


_DEFAULT_NARRATIVE_SYSTEM_PROMPT = (
    "You are an architecture analyst preparing a macro workflow overview. Rely only on supplied context."
    " Preserve the provided stage ordering and headings. Keep the tone professional and concrete."
    " Do not invent components that are not explicitly mentioned."
)


class NarrativeSynthesisLLM:
    """LLM-backed helper that rewrites the macro narrative from structured evidence."""

    def __init__(
        self,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._model = model
        self._system_prompt = system_prompt or _DEFAULT_NARRATIVE_SYSTEM_PROMPT

    @property
    def model_label(self) -> str:
        return self._model or "default"

    def __call__(
        self,
        *,
        title: str,
        orchestration_summary: str | None,
        stages: Sequence[TraceStage],
        supporting: Sequence[DirectoryInsight],
        baseline_text: str,
    ) -> str:
        prompt = self._build_prompt(
            title=title,
            orchestration_summary=orchestration_summary,
            stages=stages,
            supporting=supporting,
            baseline_text=baseline_text,
        )
        response = request_workflow_completion(
            prompt,
            model=self._model,
            system_prompt=self._system_prompt,
        )
        return response.strip()

    def _build_prompt(
        self,
        *,
        title: str,
        orchestration_summary: str | None,
        stages: Sequence[TraceStage],
        supporting: Sequence[DirectoryInsight],
        baseline_text: str,
    ) -> str:
        lines: List[str] = []
        lines.append("Produce a Markdown macro-workflow narrative for the given project.")
        lines.append("")
        lines.append(f"Title: {title}")

        if orchestration_summary:
            lines.append("")
            lines.append("High-level business summary from the orchestration agent:")
            lines.append(textwrap.indent(orchestration_summary.strip(), "  "))

        lines.append("")
        lines.append("Workflow evidence by stage:")
        for index, stage in enumerate(stages, start=1):
            lines.append(f"- Stage {index}: {stage.name}")
            lines.append(f"  Goal: {stage.goal}")
            for directory in stage.directories:
                lines.append(f"  • Directory: {directory.directory_path or '.'}")
                if directory.overview:
                    lines.append(f"    Overview: {directory.overview}")
                if directory.key_capabilities:
                    capabilities = ", ".join(directory.key_capabilities[:4])
                    lines.append(f"    Capabilities: {capabilities}")
                for profile in stage.highlighted_profiles:
                    if profile.directory_path != directory.directory_path:
                        continue
                    descriptor = _profile_summary(profile)
                    role = f" ({profile.workflow_role})" if profile.workflow_role else ""
                    lines.append(
                        f"    - Component: {profile.name}{role} [{profile.file_path}] → {descriptor}"
                    )

        if supporting:
            lines.append("")
            lines.append("Supporting directories:")
            for directory in supporting:
                overview = directory.overview or "No overview provided."
                lines.append(f"- {directory.directory_path or '.'}: {overview}")

        lines.append("")
        lines.append("Deterministic baseline narrative (retain structure, refine wording):")
        lines.append(textwrap.indent(baseline_text.strip(), "  "))
        lines.append("")
        lines.append("Return only the improved Markdown narrative.")
        return "\n".join(lines).strip() + "\n"


class TraceNarrativeComposer:
    """Compose a macro-level workflow narrative using directory and profile insights."""

    def __init__(
        self,
        *,
        stage_definitions: Sequence[StageDefinition] | None = None,
        fallback_stage: StageDefinition | None = None,
        project_name: str | None = None,
        narrative_llm: NarrativeSynthesisLLM | None = None,
    ) -> None:
        self._stage_definitions: tuple[StageDefinition, ...] = tuple(stage_definitions or DEFAULT_STAGE_DEFINITIONS)
        self._fallback_stage: StageDefinition = fallback_stage or SUPPORT_STAGE
        self._project_name = project_name
        self._narrative_llm = narrative_llm

    def compose(
        self,
        *,
        orchestration_summary: str | None,
        directories: Sequence[DirectoryInsight],
        profiles: Sequence[ProfileInsight],
        project_name: str | None = None,
    ) -> TraceNarrative:
        directory_list = list(directories)
        profile_list = list(profiles)

        title = self._build_title(project_name)

        if not directory_list:
            text = self._compose_empty_text(title, orchestration_summary)
            return TraceNarrative(
                title=title,
                text=text,
                orchestration_summary=orchestration_summary,
                stages=[],
                supporting_directories=[],
                notes=["LLM narrative skipped: no directory summaries available."] if self._narrative_llm else [],
            )

        _assign_stages(directory_list, self._stage_definitions, self._fallback_stage)
        _align_profiles_with_directories(profile_list, directory_list, self._fallback_stage.key)

        stages = _build_stage_snapshots(directory_list, profile_list, self._stage_definitions)
        supporting = [directory for directory in directory_list if directory.stage == self._fallback_stage.key]

        baseline_text = self._compose_text(
            title=title,
            orchestration_summary=orchestration_summary,
            stages=stages,
            supporting=supporting,
            fallback_stage=self._fallback_stage,
        )

        final_text = baseline_text
        notes: List[str] = []

        if self._narrative_llm is not None:
            try:
                final_text = self._narrative_llm(
                    title=title,
                    orchestration_summary=orchestration_summary,
                    stages=stages,
                    supporting=supporting,
                    baseline_text=baseline_text,
                )
                notes.append(f"Narrative synthesised via LLM model '{self._narrative_llm.model_label}'.")
            except LLMError as exc:
                notes.append(f"LLM narrative request failed ({exc}); reverted to deterministic narrative.")
                final_text = baseline_text
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Unexpected LLM failure ({exc}); reverted to deterministic narrative.")
                final_text = baseline_text

        return TraceNarrative(
            title=title,
            text=final_text,
            orchestration_summary=orchestration_summary,
            stages=stages,
            supporting_directories=supporting,
            notes=notes,
        )

    def _build_title(self, project_name: str | None) -> str:
        label = project_name or self._project_name or "Project"
        return f"{label} Macro Workflow Trace"

    def _compose_empty_text(self, title: str, orchestration_summary: str | None) -> str:
        lines: List[str] = [title, ""]
        if orchestration_summary:
            lines.append("Context captured by the orchestration agent:")
            lines.append(textwrap.indent(orchestration_summary.strip(), "  "))
            lines.append("")
        lines.append("No directory summaries were available; run directory summarisation before tracing workflows.")
        return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"

    def _compose_text(
        self,
        *,
        title: str,
        orchestration_summary: str | None,
        stages: Sequence[TraceStage],
        supporting: Sequence[DirectoryInsight],
        fallback_stage: StageDefinition,
    ) -> str:
        lines: List[str] = [title, ""]

        if orchestration_summary:
            lines.append("Context captured by the orchestration agent:")
            lines.append(textwrap.indent(orchestration_summary.strip(), "  "))
            lines.append("")

        for index, stage in enumerate(stages, start=1):
            lines.append(f"[ Stage {index}: {stage.name} ]")
            lines.append(f"Goal: {stage.goal}")
            lines.append("")

            for directory in stage.directories:
                label = _format_directory_label(directory.directory_path)
                overview = directory.overview or "Overview unavailable."
                lines.append(f"- {label} → {overview}")
                if directory.key_capabilities:
                    capability_text = ", ".join(directory.key_capabilities[:3])
                    lines.append(f"  Capabilities: {capability_text}")

                directory_profiles = [
                    profile
                    for profile in stage.highlighted_profiles
                    if profile.directory_path == directory.directory_path
                ]
                for profile in directory_profiles:
                    description = _profile_summary(profile)
                    role_suffix = f" [{profile.workflow_role}]" if profile.workflow_role else ""
                    lines.append(
                        f"    • {profile.name}{role_suffix} ({profile.file_path}) — {description}"
                    )
            lines.append("")

        if supporting:
            lines.append(f"[ {fallback_stage.name} ]")
            lines.append(f"Goal: {fallback_stage.goal}")
            lines.append("")
            for directory in supporting:
                label = _format_directory_label(directory.directory_path)
                overview = directory.overview or "Overview unavailable."
                lines.append(f"- {label} → {overview}")
            lines.append("")

        return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"


def _assign_stages(
    directories: Sequence[DirectoryInsight],
    stage_definitions: Sequence[StageDefinition],
    fallback_stage: StageDefinition,
) -> None:
    for directory in directories:
        text = _directory_search_text(directory)

        best_score = 0
        best_stage: StageDefinition | None = None
        best_hits: List[str] = []

        for stage in stage_definitions:
            score, hits = _stage_score(text, stage.keywords)
            if score > best_score:
                best_score = score
                best_stage = stage
                best_hits = hits

        if best_stage:
            directory.stage = best_stage.key
            directory.stage_reason = _stage_reason(best_hits)
            directory.matched_keywords = best_hits
        else:
            directory.stage = fallback_stage.key
            directory.stage_reason = "No matching stage keywords."
            directory.matched_keywords = []


def _align_profiles_with_directories(
    profiles: Sequence[ProfileInsight],
    directories: Sequence[DirectoryInsight],
    fallback_stage_key: str,
) -> None:
    for profile in profiles:
        match = _match_directory(profile.file_path, directories)
        if match is None:
            profile.stage = fallback_stage_key
            profile.directory_path = "."
        else:
            profile.stage = match.stage
            profile.directory_path = match.directory_path


def _match_directory(file_path: str, directories: Sequence[DirectoryInsight]) -> DirectoryInsight | None:
    normalised_file = _normalise_path(file_path)
    best: DirectoryInsight | None = None
    best_length = -1

    for directory in directories:
        directory_path = _normalise_path(directory.directory_path)
        if directory_path in {"", "."}:
            continue
        if normalised_file == directory_path or normalised_file.startswith(f"{directory_path}/"):
            length = len(directory_path)
            if length > best_length:
                best = directory
                best_length = length

    if best is not None:
        return best

    for directory in directories:
        if _normalise_path(directory.directory_path) in {"", "."}:
            return directory
    return None


def _build_stage_snapshots(
    directories: Sequence[DirectoryInsight],
    profiles: Sequence[ProfileInsight],
    stage_definitions: Sequence[StageDefinition],
) -> List[TraceStage]:
    stages: List[TraceStage] = []
    for stage in stage_definitions:
        stage_directories = [directory for directory in directories if directory.stage == stage.key]
        if not stage_directories:
            continue
        stage_profiles = [
            profile for profile in profiles if profile.stage == stage.key
        ]
        stage_profiles.sort(key=lambda item: (item.directory_path, item.file_path, item.name))
        stages.append(
            TraceStage(
                key=stage.key,
                name=stage.name,
                goal=stage.goal,
                directories=stage_directories,
                highlighted_profiles=stage_profiles,
            )
        )
    return stages


def _directory_search_text(directory: DirectoryInsight) -> str:
    parts: List[str] = [
        _normalise_path(directory.directory_path),
        (directory.overview or "").lower(),
    ]
    parts.extend(cap.lower() for cap in directory.key_capabilities)
    parts.append(_summary_text(directory.summary))
    return " ".join(part for part in parts if part)


def _stage_score(text: str, keywords: Iterable[str]) -> tuple[int, List[str]]:
    hits: List[str] = []
    score = 0
    for keyword in keywords:
        normalised = keyword.lower()
        if normalised and normalised in text:
            score += 1
            hits.append(normalised)
    return score, hits


def _stage_reason(hits: Sequence[str]) -> str:
    if not hits:
        return ""
    unique = sorted(set(hits))
    return f"Matched keywords: {', '.join(unique)}"


def _summary_text(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    parts: List[str] = []

    def _collect(value: object) -> None:
        if isinstance(value, str):
            parts.append(value.lower())
        elif isinstance(value, dict):
            for item in value.values():
                _collect(item)
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            for item in value:
                _collect(item)

    _collect(payload)
    return " ".join(parts)


def _format_directory_label(directory_path: str) -> str:
    cleaned = _normalise_path(directory_path)
    if cleaned in {"", "."}:
        return "root"
    segments = [segment.replace("_", " ").strip() for segment in cleaned.split("/")]
    return " / ".join(segment.title() for segment in segments if segment)


def _profile_summary(profile: ProfileInsight) -> str:
    candidates = [
        profile.core_identity,
        profile.business_intent,
        profile.docstring,
    ]
    for candidate in candidates:
        if candidate:
            return _first_sentence(candidate)
    return "Summary unavailable."


def _first_sentence(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    first_line = stripped.splitlines()[0].strip()
    for delimiter in ".!?":
        position = first_line.find(delimiter)
        if 0 < position < len(first_line) - 1:
            return first_line[: position + 1].strip()
    return first_line


def _normalise_path(value: str) -> str:
    cleaned = (value or "").replace("\\", "/").strip()
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    while "//" in cleaned:
        cleaned = cleaned.replace("//", "/")
    return cleaned or "."


TraceNarrativeBuilder = TraceNarrativeComposer
WorkflowSynthesizer = TraceNarrativeComposer

__all__ = [
    "DEFAULT_STAGE_DEFINITIONS",
    "NarrativeSynthesisLLM",
    "StageDefinition",
    "SUPPORT_STAGE",
    "TraceNarrativeBuilder",
    "TraceNarrativeComposer",
    "WorkflowSynthesizer",
]
