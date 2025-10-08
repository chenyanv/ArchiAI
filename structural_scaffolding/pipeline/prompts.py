from __future__ import annotations

from typing import List

from .context import L1SummaryContext, RelatedProfileSnippet

_MAX_LIST_ITEMS = 12
_MAX_RELATED_ITEMS = 5


def build_l1_messages(context: L1SummaryContext) -> List[dict[str, str]]:
    members = _format_section("Public API", context.public_members)
    calls = _format_section("Key outbound calls", context.outbound_calls)
    imports = _format_section("Imports", context.imports)
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
        "Source code:\n```python\n" + context.source_code + "\n```",
    ]

    user_content = "\n\n".join(line for line in user_lines if line)

    instruction = (
        "Role: You are a principal software architect who understands isolated components and how they participate in larger workflows.\n"
        "Task: Analyse the provided component and respond strictly as JSON with the following structure:\n"
        '{"summary":{"core_identity":"","business_intent":"","data_flow":{"inputs":[],"outputs":[]},"key_interactions":{"collaborators":[],"side_effects":[]}},"workflow_hints":{"role":"","potential_workflow_name":"","triggers":[],"outputs_to":[]}}'
        "\nPopulate each field with grounded information taken from the context. "
        "workflow_hints.role must be one of \"ENTRY_POINT\", \"KEY_STEP\", \"TERMINATOR\", or \"UTILS\". "
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


__all__ = ["build_l1_messages"]
