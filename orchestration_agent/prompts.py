from __future__ import annotations

from typing import Iterable, List

from .state import DirectorySummary, TableSnapshot


def build_system_prompt() -> str:
    return (
        "You are a senior architecture analyst tasked with mapping the primary business "
        "logic within a codebase. Use the provided directory-level summaries (overview, key capabilities, "
        "entry points, dependencies, follow-up questions) to infer the main workflows and business domains. "
        "Ground every statement in the supplied context, call out uncertainties, and focus "
        "on actionable insights."
    )


def build_business_summary_prompt(
    directory_summaries: Iterable[DirectorySummary],
    table_snapshots: Iterable[TableSnapshot],  # retained for interface compatibility; ignored intentionally
) -> str:
    _ = table_snapshots  # explicitly unused; business logic inferred solely from directory summaries
    directory_section = _format_directory_summaries(directory_summaries)

    instruction = (
        "Analyse the repository context and produce a concise narrative covering:\n"
        "1. Core business capabilities the codebase supports.\n"
        "2. Key workflows or orchestrations implied by the top-level directories.\n"
        "3. Notable gaps or follow-up questions for deeper discovery.\n"
        "Keep the response under 300 words, use paragraphs (no bullet lists), and "
        "explicitly reference directory paths when citing evidence."
    )

    return f"{instruction}\n\n=== Directory Summaries ===\n{directory_section}"


def _format_directory_summaries(directory_summaries: Iterable[DirectorySummary]) -> str:
    lines: List[str] = []
    for summary in directory_summaries:
        core_summary = summary.summary or {}
        overview = core_summary.get("overview", "Overview unavailable.")
        capabilities = _comma_join(core_summary.get("key_capabilities"))
        entry_points = _comma_join(core_summary.get("notable_entry_points"))
        dependencies = _comma_join(core_summary.get("dependencies"))
        follow_up = _comma_join(core_summary.get("follow_up"))

        lines.append(
            f"- {summary.directory_path} (root={summary.root_path or '(unspecified)'}, files={summary.file_count})\n"
            f"  overview: {overview}\n"
            f"  key_capabilities: {capabilities or 'None listed'}\n"
            f"  notable_entry_points: {entry_points or 'None'}\n"
            f"  dependencies: {dependencies or 'None highlighted'}\n"
            f"  follow_up: {follow_up or 'None noted'}"
        )

    if not lines:
        return "(no directory summaries available)"
    return "\n".join(lines)
 

def _comma_join(values: object) -> str:
    if not values:
        return ""
    if isinstance(values, (list, tuple, set)):
        text_items = [str(item) for item in values if item is not None]
        return ", ".join(text_items)
    return str(values)
