from __future__ import annotations

import json
from textwrap import indent
from typing import Iterable, List, Sequence

from structural_scaffolding.pipeline.llm import (
    LLMError,
    request_workflow_completion,
)
from workflow_tracing.models import DirectoryInsight, ProfileInsight

from .models import (
    ComponentExploration,
    ComponentOption,
    PlannerComponent,
    PlannerOutput,
    TraceSeed,
)

_DEFAULT_PLANNER_SYSTEM = (
    "You are a senior solutions architect onboarding a new engineer. Translate the component inventory into a "
    "coherent, stage-by-stage story of how the system delivers value. Highlight how data and control move between "
    "stages while grounding every claim in the supplied evidence."
)
_DEFAULT_ANALYST_SYSTEM = (
    "You help engineers inspect existing implementation details for a requested component. Use the supplied "
    "trace tokens to explain how the workflow is realised today, surface options or variants, and highlight "
    "traceable artefacts (files, profiles) that the user can investigate next."
)


class TopLevelPlanner:
    """Synthesises the macro narrative and capability components."""

    def __init__(
        self,
        *,
        component_limit: int,
        enable_llm: bool = True,
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._component_limit = max(component_limit, 1)
        self._enable_llm = enable_llm
        self._model = model
        self._system_prompt = system_prompt or _DEFAULT_PLANNER_SYSTEM

    def __call__(
        self,
        summary: str | None,
        directories: Sequence[DirectoryInsight],
        profiles: Sequence[ProfileInsight],
        available_seeds: Sequence[TraceSeed],
    ) -> PlannerOutput:
        if not self._enable_llm:
            return self._fallback(summary, directories)

        prompt = _build_planner_prompt(summary, directories, profiles, available_seeds, self._component_limit)
        try:
            response = request_workflow_completion(
                prompt,
                model=self._model,
                system_prompt=self._system_prompt,
            )
            return _parse_planner_response(response, directories, self._component_limit)
        except (LLMError, json.JSONDecodeError, ValueError) as exc:
            return self._fallback(summary, directories, failure_reason=str(exc))

    def _fallback(
        self,
        summary: str | None,
        directories: Sequence[DirectoryInsight],
        *,
        failure_reason: str | None = None,
    ) -> PlannerOutput:
        headline_parts: List[str] = []
        if summary:
            headline_parts.append(summary.strip())
        else:
            headline_parts.append(
                "LLM planning unavailable; composing summary from directory-level metadata."
            )

        notes: List[str] = []
        if failure_reason:
            notes.append(f"Planner fallback activated (reason: {failure_reason}).")

        components: List[PlannerComponent] = []
        for idx, directory in enumerate(directories[: self._component_limit], start=1):
            description = directory.overview or "Overview not captured."
            keywords = list(directory.key_capabilities or [])
            components.append(
                PlannerComponent(
                    name=f"{idx}. {directory.directory_path or directory.root_path or 'root'}",
                    description=description,
                    keywords=keywords,
                    trace_tokens=[directory.directory_path or "."],
                    evidence=[directory.directory_path or ""],
                )
            )

        if not components:
            components.append(
                PlannerComponent(
                    name="Repository Overview",
                    description="Directory summaries unavailable; gather structural scaffolding data first.",
                )
            )

        return PlannerOutput(
            summary="\n".join(headline_parts),
            components=components,
            notes=notes,
        )


class ComponentAnalyst:
    """Explains implementation specifics for a given component query."""

    def __init__(
        self,
        *,
        enable_llm: bool = True,
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._enable_llm = enable_llm
        self._model = model
        self._system_prompt = system_prompt or _DEFAULT_ANALYST_SYSTEM

    def explore(
        self,
        query: str,
        *,
        directories: Sequence[DirectoryInsight],
        profiles: Sequence[ProfileInsight],
        active_seeds: Sequence[TraceSeed],
        source_tokens: Sequence[str],
    ) -> ComponentExploration:
        if not self._enable_llm:
            return self._fallback(query, directories, profiles, active_seeds)

        prompt = _build_analyst_prompt(query, directories, profiles, active_seeds, source_tokens)
        try:
            response = request_workflow_completion(
                prompt,
                model=self._model,
                system_prompt=self._system_prompt,
            )
            return _parse_component_response(query, response, active_seeds)
        except (LLMError, json.JSONDecodeError, ValueError) as exc:
            return self._fallback(query, directories, profiles, active_seeds, failure_reason=str(exc))

    def _fallback(
        self,
        query: str,
        directories: Sequence[DirectoryInsight],
        profiles: Sequence[ProfileInsight],
        active_seeds: Sequence[TraceSeed],
        *,
        failure_reason: str | None = None,
    ) -> ComponentExploration:
        summary_bits: List[str] = []
        if failure_reason:
            summary_bits.append(f"LLM analysis unavailable (reason: {failure_reason}).")
        summary_bits.append("Falling back to deterministic context matching.")

        options: List[ComponentOption] = []
        for directory in directories:
            description = directory.overview or "No overview recorded."
            workflow = "Key capabilities: " + ", ".join(directory.key_capabilities[:5]) if directory.key_capabilities else "Key capabilities not captured."
            options.append(
                ComponentOption(
                    title=f"Directory: {directory.directory_path or directory.root_path or '.'}",
                    rationale=description,
                    workflow=workflow,
                    trace_tokens=[directory.directory_path or "."],
                )
            )

        for profile in profiles:
            description = profile.business_intent or profile.core_identity or profile.workflow_role
            workflow = profile.docstring or "Docstring not captured."
            options.append(
                ComponentOption(
                    title=f"Profile: {profile.name}",
                    rationale=description or "Business intent not recorded.",
                    workflow=workflow,
                    trace_tokens=[profile.profile_id],
                )
            )

        seeds = list(active_seeds)
        return ComponentExploration(
            query=query,
            analysis=" ".join(summary_bits),
            options=options[:3] if options else [],
            trace_seeds=seeds,
            source_tokens=[seed.token for seed in seeds],
        )


def _build_planner_prompt(
    orchestration_summary: str | None,
    directories: Sequence[DirectoryInsight],
    profiles: Sequence[ProfileInsight],
    seeds: Sequence[TraceSeed],
    component_limit: int,
) -> str:
    directory_block = []
    for directory in directories:
        directory_block.append(
            json.dumps(
                {
                    "path": directory.directory_path or directory.root_path or ".",
                    "overview": directory.overview,
                    "key_capabilities": directory.key_capabilities,
                },
                ensure_ascii=False,
            )
        )

    profile_block = []
    for profile in profiles[: component_limit * 3]:
        profile_block.append(
            json.dumps(
                {
                    "profile_id": profile.profile_id,
                    "name": profile.name,
                    "file_path": profile.file_path,
                    "business_intent": profile.business_intent,
                    "workflow_role": profile.workflow_role,
                },
                ensure_ascii=False,
            )
        )

    token_map = []
    for seed in seeds:
        token_map.append(
            json.dumps(
                {
                    "token": seed.token,
                    "label": seed.label,
                    "kind": seed.kind,
                    "description": seed.description,
                },
                ensure_ascii=False,
            )
        )

    instruction = (
        "Synthesize the macro-level workflow from the supplied repository context. Identify the sequential stages "
        "that carry a request from intake to completion, weave the key components into each stage, and explain how "
        "outputs hand off to the next stage.\n\n"
        "Return JSON with this schema:\n"
        "{\n"
        '  "summary": "High-level narrative (<=6 sentences) that walks through each stage by name, citing the main directories or profiles powering that hand-off.",\n'
        '  "components": [\n'
        "    {\n"
        '      "name": "Stage N — Descriptive title",\n'
        '      "description": "2-4 sentence narrative describing what happens, which components act (cite specific directories or profiles), and how the stage hands off.",\n'
        '      "keywords": ["key components, directories, outcomes"],\n'
        '      "trace_tokens": ["tokens taken from the provided list that anchor this stage"],\n'
        '      "evidence": ["directories or files from the context that substantiate the narrative"]\n'
        "    }\n"
        "  ],\n"
        '  "notes": ["optional uncertainties or next-investigation items"]\n'
        "}\n\n"
        "Guidance:\n"
        f"- Deliver no more than {component_limit} stages that together read like an assembly guide rather than a parts list.\n"
        "- Stage descriptions must be paragraph narrative, not bullet lists.\n"
        "- Explicitly call out how data or control flows between stages and what each stage produces.\n"
        "- Group components under the stage where they do the bulk of the work and mention their roles clearly, referencing directory names where possible.\n"
        "- Only use trace tokens that appear in the provided list; if none apply, leave the array empty.\n"
        "- Cite directories or files in evidence so the reader can inspect the implementation.\n"
        "- Respond with JSON only."
    )

    parts: List[str] = [instruction]
    if orchestration_summary:
        parts.append("=== Orchestration Narrative ===")
        parts.append(orchestration_summary.strip())

    if directory_block:
        parts.append("=== Directory Summaries ===")
        parts.append("\n".join(directory_block))

    if profile_block:
        parts.append("=== Representative Profiles ===")
        parts.append("\n".join(profile_block))

    if token_map:
        parts.append("=== Trace Tokens ===")
        parts.append("\n".join(token_map))

    return "\n\n".join(parts)


def _parse_planner_response(
    response: str,
    directories: Sequence[DirectoryInsight],
    component_limit: int,
) -> PlannerOutput:
    payload = _extract_json_fragment(response)
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Planner response must be a JSON object.")

    summary = str(data.get("summary") or "").strip()
    components_payload = data.get("components")
    notes_payload = data.get("notes") or []
    notes = [str(note).strip() for note in notes_payload if str(note).strip()]

    components: List[PlannerComponent] = []
    if isinstance(components_payload, list):
        for item in components_payload[:component_limit]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            description = str(item.get("description") or "").strip()
            if not name or not description:
                continue
            keywords = [str(value).strip() for value in item.get("keywords", []) if str(value).strip()]
            trace_tokens = [str(value).strip() for value in item.get("trace_tokens", []) if str(value).strip()]
            evidence = [str(value).strip() for value in item.get("evidence", []) if str(value).strip()]
            components.append(
                PlannerComponent(
                    name=name,
                    description=description,
                    keywords=keywords,
                    trace_tokens=trace_tokens,
                    evidence=evidence,
                )
            )

    if not components:
        # Basic fallback if JSON parsed but no valid components.
        planner = TopLevelPlanner(component_limit=component_limit, enable_llm=False)
        return planner(
            summary if summary else None,
            directories,
            [],
            [],
        )

    return PlannerOutput(summary=summary, components=components, notes=notes)


def _extract_json_fragment(raw_response: str) -> str:
    text = (raw_response or "").strip()
    if not text:
        raise ValueError("Planner response was empty.")

    if text.startswith("```"):
        lines = text.splitlines()
        fence = lines[0]
        if fence.startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Planner response did not contain a JSON object.")

    return text[start : end + 1]


def _build_analyst_prompt(
    query: str,
    directories: Sequence[DirectoryInsight],
    profiles: Sequence[ProfileInsight],
    seeds: Sequence[TraceSeed],
    source_tokens: Sequence[str],
) -> str:
    instruction = (
        "Analyse the requested component keyword using the supplied implementation snippets. "
        "Produce a JSON object describing what exists today, outline 1-3 current implementation options, "
        "and suggest trace seeds for drilling deeper. "
        "If multiple approaches exist, differentiate them clearly."
    )

    directory_context = []
    for directory in directories:
        directory_context.append(
            json.dumps(
                {
                    "token": directory.directory_path or directory.root_path or ".",
                    "overview": directory.overview,
                    "key_capabilities": directory.key_capabilities,
                },
                ensure_ascii=False,
            )
        )

    profile_context = []
    for profile in profiles:
        profile_context.append(
            json.dumps(
                {
                    "token": profile.profile_id,
                    "name": profile.name,
                    "file_path": profile.file_path,
                    "business_intent": profile.business_intent,
                    "workflow_role": profile.workflow_role,
                    "docstring": profile.docstring,
                },
                ensure_ascii=False,
            )
        )

    seed_context = []
    for seed in seeds:
        seed_context.append(
            json.dumps(
                {
                    "token": seed.token,
                    "kind": seed.kind,
                    "label": seed.label,
                    "description": seed.description,
                    "file_path": seed.file_path,
                    "profile_id": seed.profile_id,
                },
                ensure_ascii=False,
            )
        )

    prompt_lines = [
        instruction,
        "User query: %s" % query,
        "Trace tokens available for reference: %s" % list(source_tokens),
        "Response schema:",
        json.dumps(
            {
                "analysis": "Explain what exists today for this component (max 150 words).",
                "options": [
                    {
                        "title": "Option name (existing implementation or variant).",
                        "rationale": "Why this option is relevant to the query.",
                        "workflow": "Describe how the implementation flows across the code.",
                        "trace_tokens": ["list of trace tokens involved"],
                        "considerations": ["risks or surrounding context"],
                    }
                ],
                "trace_seeds": [
                    {
                        "token": "existing or new token for next drill-down",
                        "label": "User-facing label",
                        "kind": "directory|profile|call",
                        "description": "Why this token matters",
                        "aliases": ["optional keyword triggers"],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        "=== Directory Context ===",
        "\n".join(directory_context) if directory_context else "(none)",
        "=== Profile Context ===",
        "\n".join(profile_context) if profile_context else "(none)",
        "=== Seed Context ===",
        "\n".join(seed_context) if seed_context else "(none)",
        "Respond with JSON only.",
    ]
    return "\n\n".join(prompt_lines)


def _parse_component_response(
    query: str,
    response: str,
    backing_seeds: Sequence[TraceSeed],
) -> ComponentExploration:
    data = json.loads(response)
    if not isinstance(data, dict):
        raise ValueError("Analyst response must be a JSON object.")

    analysis = str(data.get("analysis") or "").strip()
    options_payload = data.get("options") or []
    seeds_payload = data.get("trace_seeds") or []

    options: List[ComponentOption] = []
    if isinstance(options_payload, list):
        for item in options_payload[:3]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            rationale = str(item.get("rationale") or "").strip()
            workflow = str(item.get("workflow") or "").strip()
            if not title or not workflow:
                continue
            trace_tokens = [str(value).strip() for value in item.get("trace_tokens", []) if str(value).strip()]
            considerations = [
                str(value).strip() for value in item.get("considerations", []) if str(value).strip()
            ]
            options.append(
                ComponentOption(
                    title=title,
                    rationale=rationale,
                    workflow=workflow,
                    trace_tokens=trace_tokens,
                    considerations=considerations,
                )
            )

    trace_seeds: List[TraceSeed] = list(backing_seeds)
    if isinstance(seeds_payload, list):
        for item in seeds_payload:
            if not isinstance(item, dict):
                continue
            token = str(item.get("token") or "").strip()
            label = str(item.get("label") or "").strip()
            kind = str(item.get("kind") or "").strip() or "call"
            description = str(item.get("description") or "").strip() or None
            if not token or not label:
                continue
            aliases = [str(value).strip() for value in item.get("aliases", []) if str(value).strip()]
            metadata = {}
            publisher = TraceSeed(
                token=token,
                kind=kind,
                label=label,
                description=description,
                aliases=aliases,
                metadata=metadata,
            )
            trace_seeds.append(publisher)

    source_tokens = [seed.token for seed in trace_seeds]

    return ComponentExploration(
        query=query,
        analysis=analysis,
        options=options,
        trace_seeds=trace_seeds,
        source_tokens=source_tokens,
    )


__all__ = ["ComponentAnalyst", "TopLevelPlanner"]
