from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class SummaryLevel(str, Enum):
    NONE = "NONE"
    LEVEL_1 = "LEVEL_1"
    LEVEL_2_IN_PROGRESS = "LEVEL_2_IN_PROGRESS"
    LEVEL_2_COMPLETED = "LEVEL_2_COMPLETED"


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
    summary_level: SummaryLevel = SummaryLevel.NONE
    summaries: Dict[str, str] = field(default_factory=dict)
    parameters: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)
    children: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        # dataclasses.asdict preserves nested slots and ensures JSON serialization.
        data = asdict(self)
        data["summary_level"] = self.summary_level.value
        return data


__all__ = ["Profile", "SummaryLevel"]
