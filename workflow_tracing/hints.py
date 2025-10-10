from __future__ import annotations

import re
from typing import List


def extract_directory_hints(summary: str | None) -> List[str]:
    """Pull potential directory keywords from a narrative summary."""
    if not summary:
        return []

    candidates: set[str] = set()

    bold_matches = re.findall(r"\*\*([^*]+)\*\*", summary)
    candidates.update(_normalise(item) for item in bold_matches)

    slash_matches = re.findall(r"([A-Za-z0-9_\\-]+)/", summary)
    candidates.update(_normalise(item) for item in slash_matches)

    directory_matches = re.findall(r"([A-Za-z0-9_\\-]+)\\s+directory", summary, flags=re.IGNORECASE)
    candidates.update(_normalise(item) for item in directory_matches)

    cleaned = [item for item in candidates if item]
    cleaned.sort()
    return cleaned


def _normalise(value: str) -> str:
    cleaned = (value or "").strip().lower()
    cleaned = cleaned.strip("*").strip()
    cleaned = cleaned.replace("\\", "/")
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


__all__ = ["extract_directory_hints"]

