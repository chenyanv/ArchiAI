from __future__ import annotations

from typing import List

from .context import L1SummaryContext, RelatedProfileSnippet

_MAX_LIST_ITEMS = 12
_MAX_RELATED_ITEMS = 5


def build_l1_messages(context: L1SummaryContext) -> List[dict[str, str]]:
    members = _format_section("Public API", context.public_members)
    calls = _format_section("Key outbound calls", context.outbound_calls)
    imports = _format_section("Imports", context.imports)
    related = _format_related_profiles(context.related_profiles)

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
        related,
        "Source code:\n```python\n" + context.source_code + "\n```",
    ]

    user_content = "\n\n".join(line for line in user_lines if line)

    return [
        {
            "role": "system",
            "content": (
                "You are a senior software architect. Provide a concise Level 1 summary that explains "
                "the role, responsibilities, and collaboration points of the target component. "
                "Do not repeat the prompt, focus on purpose, major behaviours, and the interfaces it exposes."
            ),
        },
        {
            "role": "user",
            "content": user_content,
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
