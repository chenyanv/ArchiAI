from __future__ import annotations

from typing import List

from .context import (
    DirectorySummaryContext,
    EntryPointCandidateSnippet,
    L1SummaryContext,
    RelatedProfileSnippet,
)

_MAX_LIST_ITEMS = 12
_MAX_RELATED_ITEMS = 5


def build_l1_messages(context: L1SummaryContext) -> List[dict[str, str]]:
    members = _format_section("Public API", context.public_members)
    calls = _format_section("Key outbound calls", context.outbound_calls)
    imports = _format_section("Imports", context.imports)
    candidates = _format_entry_point_candidates(context.entry_point_candidates)
    # NOTE: Related profile context is intentionally omitted to keep the prompt lean.

    docstring = context.docstring.strip() if context.docstring else "(none)"

    user_lines = [
        f"Target: {context.display_name}",
        f"Profile ID: {context.profile_id}",
        f"Kind: {context.kind}",
        f"File: {context.file_path}",
        f"Docstring: {docstring}",
        members,
        calls,
        imports,
        candidates,
        "Source code:\n```python\n" + context.source_code + "\n```",
    ]

    user_content = "\n\n".join(line for line in user_lines if line)

    instruction = (
        "Role: You are a principal software architect who understands isolated components and how they participate in larger workflows.\n"
        "Task: Analyse the provided component and respond strictly as JSON with the following structure:\n"
        '{"summary":{"core_identity":"","business_intent":"","data_flow":{"inputs":[],"outputs":[]},"key_interactions":{"collaborators":[],"side_effects":[]}},"workflow_hints":{"role":"","potential_workflow_name":"","triggers":[],"outputs_to":[]},"entry_point":{"profile_id":"","display_name":"","confidence":"","reasons":""}}'
        "\nPopulate each field with grounded information taken from the context. "
        "workflow_hints.role must be one of \"ENTRY_POINT\", \"KEY_STEP\", \"TERMINATOR\", or \"UTILS\". "
        "entry_point.profile_id must either be one of the candidate profile IDs listed in the context or an empty string when no entry point exists. "
        "If no candidate qualifies as a workflow entry, set entry_point to null. "
        "Set confidence to one of HIGH, MEDIUM, or LOW. Provide concise reasons grounded in evidence. "
        "Use descriptive sentences for string fields. When evidence is missing, set the string value to \"Unknown\" and leave arrays empty. "
        "Only add triggers or outputs_to entries when the evidence supports them; otherwise leave the arrays empty (especially for non-KEY_STEP roles). "
        "Do not add extra keys, prose, Markdown, or commentary."
    )

    return [
        {
            "role": "system",
            "content": (
                "You are a principal workflow systems architect. Interpret the supplied metadata and source code, "
                "ground every statement in evidence, prefer 'Unknown' to speculation, and obey the response format exactly."
            ),
        },
        {
            "role": "user",
            "content": instruction + "\n\n=== Context ===\n" + user_content,
        },
    ]


def build_directory_messages(context: DirectorySummaryContext) -> List[dict[str, str]]:
    instruction = (
        "You are a principal software architect reviewing a directory of source files. "
        "Your task is to analyse the provided file-level summaries and produce an aggregated "
        "directory overview. Respond strictly with a JSON object that matches this schema:\n"
        '{"directory":"","overview":"","key_capabilities":[],"notable_entry_points":[],"dependencies":[],"follow_up":[]}'
        "\nFill every field using only evidence from the context. "
        "overview should be a concise paragraph (<=3 sentences). "
        "key_capabilities should list the most important responsibilities in priority order. "
        "notable_entry_points should list file names or callables that initiate workflows (if none, leave the array empty). "
        "dependencies should capture external systems, services, or important collaborators. "
        "follow_up should contain open questions or gaps for further investigation. "
        "Do not invent facts or add extra keys. Use 'Unknown' when evidence is missing."
    )

    file_section = _format_directory_files(context.files)
    root_path = context.root_path or "(unspecified)"

    user_content = (
        f"Root path: {root_path}\n"
        f"Directory: {context.directory_path}\n"
        f"File count: {len(context.files)}\n"
        "\n=== File Summaries ===\n"
        f"{file_section}"
    )

    return [
        {
            "role": "system",
            "content": (
                "You are a pragmatic architecture analyst. Ground all statements in the supplied evidence, "
                "prefer 'Unknown' to speculation, and return JSON matching the requested schema."
            ),
        },
        {
            "role": "user",
            "content": instruction + "\n\n=== Context ===\n" + user_content,
        },
    ]


def _format_section(title: str, items: List[str]) -> str:
    if not items:
        return f"{title}: (none)"

    unique_items = items[:_MAX_LIST_ITEMS]
    bullet_lines = "\n".join(f"- {item}" for item in unique_items)
    if len(items) > _MAX_LIST_ITEMS:
        bullet_lines += "\n- ..."

    return f"{title}:\n{bullet_lines}"


def _format_related_profiles(related_profiles: List[RelatedProfileSnippet]) -> str:
    # Historical helper retained as documentation of the earlier approach where we
    # threaded related profiles (depth 1) into the prompt. Calling code now skips
    # this to avoid recursively expanding context.
    if not related_profiles:
        return "Related profiles (depth 1): (none)"

    lines: List[str] = ["Related profiles (depth 1):"]
    for snippet in related_profiles[:_MAX_RELATED_ITEMS]:
        doc = snippet.docstring.strip() if snippet.docstring else "(none)"
        lines.append(
            (
                f"- {snippet.name} [{snippet.kind}] id={snippet.profile_id} file={snippet.file_path}\n"
                f"  Docstring: {doc}\n"
                f"  Source:\n```python\n{snippet.source_code}\n```"
            )
        )

    if len(related_profiles) > _MAX_RELATED_ITEMS:
        lines.append("- ...")

    return "\n".join(lines)


def _format_entry_point_candidates(candidates: List[EntryPointCandidateSnippet]) -> str:
    if not candidates:
        return "Candidate entry points: (none detected)"

    lines: List[str] = ["Candidate entry points:"]
    for idx, candidate in enumerate(candidates, start=1):
        visibility = "public" if candidate.is_public else "private"
        calls = ", ".join(candidate.outbound_calls) if candidate.outbound_calls else "none"
        doc = candidate.docstring.strip() if candidate.docstring else "(no docstring)"
        lines.append(
            (
                f"{idx}. profile_id={candidate.profile_id} "
                f"name={candidate.name} [{candidate.kind}, {visibility}] "
                f"calls={candidate.call_count} [{calls}] "
                f"docstring={doc}"
            )
        )

    return "\n".join(lines)


def _format_directory_files(files: List["DirectoryFileSummary"]) -> str:
    if not files:
        return "(no files with L1 summaries)"

    lines: List[str] = []
    for idx, file_summary in enumerate(files, start=1):
        summary = file_summary.summary or {}
        workflow_hints = file_summary.workflow_hints or {}
        entry_point = file_summary.entry_point or {}

        core_identity = summary.get("core_identity") or summary.get("business_intent") or "Unknown"
        business_intent = summary.get("business_intent", "Unknown")
        data_flow = summary.get("data_flow") or {}
        inputs = ", ".join(data_flow.get("inputs", [])) if isinstance(data_flow, dict) else "Unknown"
        outputs = ", ".join(data_flow.get("outputs", [])) if isinstance(data_flow, dict) else "Unknown"
        hints_role = workflow_hints.get("role", "Unknown") if isinstance(workflow_hints, dict) else "Unknown"
        entry_id = entry_point.get("profile_id", "None") if isinstance(entry_point, dict) else "None"

        lines.append(
            (
                f"{idx}. File: {file_summary.file_path}\n"
                f"   Summary core_identity: {core_identity}\n"
                f"   Summary business_intent: {business_intent}\n"
                f"   Data inputs: {inputs or 'Unknown'}\n"
                f"   Data outputs: {outputs or 'Unknown'}\n"
                f"   Workflow role: {hints_role}\n"
                f"   Suggested entry point: {entry_id}"
            )
        )

    return "\n".join(lines)


__all__ = ["build_l1_messages", "build_directory_messages"]
