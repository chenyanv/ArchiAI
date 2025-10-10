from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, TypedDict


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Runtime configuration for the orchestration agent."""

    database_url: Optional[str] = None
    root_path: Optional[str] = None
    max_directories: int = 25
    include_row_counts: bool = True
    summary_model: Optional[str] = None
    verbose: bool = False


@dataclass(frozen=True, slots=True)
class DirectorySummary:
    """View of a directory-level summary stored in directory_summaries."""

    root_path: str
    directory_path: str
    summary: dict[str, Any]
    file_count: int
    source_files: List[str]


@dataclass(frozen=True, slots=True)
class TableColumn:
    """Schema detail for a database table column."""

    name: str
    type_: str
    nullable: bool


@dataclass(frozen=True, slots=True)
class TableSnapshot:
    """Snapshot of a database table's schema plus optional row count."""

    name: str
    columns: List[TableColumn]
    row_count: Optional[int]


class AgentState(TypedDict, total=False):
    """Shared state that flows through the LangGraph orchestration pipeline."""

    config: AgentConfig
    directory_summaries: List[DirectorySummary]
    table_snapshots: List[TableSnapshot]
    business_summary: str
    events: List[str]
    errors: List[str]
