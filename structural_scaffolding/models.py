from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass(slots=True)
class Profile:
    """Immutable structural profile for a function, method, or class."""

    id: str
    kind: str
    file_path: str
    function_name: Optional[str]
    class_name: Optional[str]
    start_line: int
    end_line: int
    source_code: str
    parent_id: Optional[str] = None
    docstring: Optional[str] = None
    parameters: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)
    children: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        # dataclasses.asdict preserves nested slots and ensures JSON serialization.
        return asdict(self)


__all__ = ["Profile"]
