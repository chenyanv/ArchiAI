"""Single workspace representing an analyzed repository."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from structural_scaffolding import ProfileExtractor
from structural_scaffolding.database import persist_profiles
from tools.graph_cache import save_graph


@dataclass
class Workspace:
    """A workspace representing a single analyzed repository.

    Each workspace has:
    - source/: The extracted source code
    - results/: Analysis outputs (plan, etc.)
    - Data stored in PostgreSQL (profiles, call graph)
    """

    root: Path
    owner: str
    repo: str
    branch: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def workspace_id(self) -> str:
        """Unique identifier for this workspace."""
        return f"{self.owner}-{self.repo}"

    @property
    def source_dir(self) -> Path:
        """Path to the extracted source code."""
        return self.root / "source"

    @property
    def database_url(self) -> str:
        """PostgreSQL database URL (uses environment default)."""
        from structural_scaffolding.database import resolve_database_url
        return resolve_database_url(None)

    @property
    def results_dir(self) -> Path:
        """Path to analysis results."""
        return self.root / "results"

    @property
    def plan_path(self) -> Path:
        """Path to the orchestration plan JSON."""
        return self.results_dir / "plan.json"

    @property
    def name(self) -> str:
        """Human-readable name for this workspace."""
        return f"{self.owner}/{self.repo}"

    @property
    def is_indexed(self) -> bool:
        """Check if the workspace has been indexed (profiles AND call graph exist)."""
        from structural_scaffolding.database import ProfileRecord, create_session
        from sqlalchemy import select
        from tools.graph_cache import graph_exists

        session = create_session()
        try:
            stmt = select(ProfileRecord.id).where(ProfileRecord.workspace_id == self.workspace_id).limit(1)
            has_profiles = session.execute(stmt).first() is not None
        finally:
            session.close()

        # Must have both profiles AND call graph
        return has_profiles and graph_exists(self.workspace_id)

    @property
    def has_source(self) -> bool:
        """Check if source code has been downloaded."""
        return self.source_dir.exists() and any(self.source_dir.iterdir())

    def build_index(self, ignored_dirs: Optional[list[str]] = None) -> int:
        """Run the indexing pipeline on the source code.

        Args:
            ignored_dirs: Directories to ignore during extraction

        Returns:
            Number of profiles extracted
        """
        if not self.has_source:
            raise RuntimeError(f"No source code found at {self.source_dir}")

        # Create results directories
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # Default ignored directories
        if ignored_dirs is None:
            ignored_dirs = [
                "node_modules", ".git", "__pycache__", ".venv", "venv",
                "dist", "build", ".tox", ".pytest_cache",
            ]

        # Extract profiles
        extractor = ProfileExtractor(root=self.source_dir, ignored_dirs=ignored_dirs)
        profiles = extractor.extract()

        # Persist to PostgreSQL with workspace_id
        profiles.sort(key=lambda p: p.id)
        stored = persist_profiles(profiles, workspace_id=self.workspace_id)

        # Save call graph to database
        call_graph = extractor.call_graph
        if call_graph is not None:
            save_graph(self.workspace_id, call_graph.graph)

        return stored

    def get_metadata(self) -> Dict[str, Any]:
        """Get workspace metadata for display/storage."""
        return {
            "workspace_id": self.workspace_id,
            "owner": self.owner,
            "repo": self.repo,
            "branch": self.branch,
            "root": str(self.root),
            "created_at": self.created_at.isoformat(),
            "is_indexed": self.is_indexed,
            "has_source": self.has_source,
        }

    def __repr__(self) -> str:
        status = "indexed" if self.is_indexed else "not indexed"
        return f"Workspace({self.name}, {status})"


__all__ = ["Workspace"]
