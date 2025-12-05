"""Workspace manager for handling multiple repository workspaces."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from .github import download_tarball, parse_github_url
from .workspace import Workspace


def get_default_base_dir() -> Path:
    """Get the default base directory for workspaces.

    Uses ~/.archai/workspaces/ or ARCHAI_WORKSPACES_DIR env var.
    """
    env_dir = os.getenv("ARCHAI_WORKSPACES_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".archai" / "workspaces"


class WorkspaceManager:
    """Manages multiple repository workspaces.

    Handles:
    - Creating new workspaces from GitHub URLs
    - Listing existing workspaces
    - Finding workspaces by name
    """

    def __init__(self, base_dir: Optional[Path] = None):
        """Initialize the workspace manager.

        Args:
            base_dir: Base directory for workspaces.
                      Defaults to ~/.archai/workspaces/
        """
        self.base_dir = base_dir or get_default_base_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _workspace_dir(self, owner: str, repo: str) -> Path:
        """Get the directory for a specific workspace."""
        # Use owner-repo format for directory name
        return self.base_dir / f"{owner}-{repo}"

    def get_or_create(
        self,
        github_url: str,
        *,
        force_download: bool = False,
    ) -> Workspace:
        """Get an existing workspace or create a new one from a GitHub URL.

        Args:
            github_url: GitHub URL to analyze
            force_download: If True, re-download even if workspace exists

        Returns:
            Workspace instance (source downloaded, ready to index)
        """
        owner, repo, branch = parse_github_url(github_url)
        workspace_dir = self._workspace_dir(owner, repo)

        workspace = Workspace(
            root=workspace_dir,
            owner=owner,
            repo=repo,
            branch=branch,
        )

        # Download source if needed
        if force_download or not workspace.has_source:
            download_tarball(owner, repo, workspace_dir, branch)

        return workspace

    def get(self, owner: str, repo: str) -> Optional[Workspace]:
        """Get an existing workspace by owner/repo.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            Workspace if it exists, None otherwise
        """
        workspace_dir = self._workspace_dir(owner, repo)
        if not workspace_dir.exists():
            return None

        return Workspace(
            root=workspace_dir,
            owner=owner,
            repo=repo,
        )

    def list_workspaces(self) -> List[Workspace]:
        """List all existing workspaces.

        Returns:
            List of Workspace instances
        """
        workspaces = []

        if not self.base_dir.exists():
            return workspaces

        for path in self.base_dir.iterdir():
            if not path.is_dir():
                continue

            # Parse owner-repo from directory name
            name = path.name
            if "-" not in name:
                continue

            # Handle repos with dashes in the name
            parts = name.split("-", 1)
            if len(parts) != 2:
                continue

            owner, repo = parts
            workspaces.append(Workspace(root=path, owner=owner, repo=repo))

        return workspaces

    def delete(self, owner: str, repo: str) -> bool:
        """Delete a workspace.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            True if deleted, False if not found
        """
        import shutil

        workspace_dir = self._workspace_dir(owner, repo)
        if not workspace_dir.exists():
            return False

        shutil.rmtree(workspace_dir)
        return True


__all__ = ["WorkspaceManager", "get_default_base_dir"]
