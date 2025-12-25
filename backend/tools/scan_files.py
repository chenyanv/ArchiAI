"""Tool to scan workspace for non-code assets like models, configs, and extensions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Directories to ignore during scanning
_IGNORE_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    ".idea", "dist", "build", ".egg-info", ".tox", ".pytest_cache",
    ".mypy_cache", ".ruff_cache",
})


class ScanFilesInput(BaseModel):
    patterns: List[str] = Field(
        ...,
        min_length=1,
        description=(
            "List of glob patterns to search for. "
            "E.g., ['*.onnx', '*.pt'] for models, ['Dockerfile', '*.yaml'] for infra, "
            "['*.so', '*.cpp'] for native extensions."
        ),
    )
    max_results: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of files to return. Default is 50.",
    )


def _get_source_dir(workspace_id: str) -> Path:
    """Get source directory for a workspace."""
    # Delayed import to avoid circular dependency
    from workspace import WorkspaceManager

    if "-" not in workspace_id:
        raise ValueError(f"Invalid workspace_id format: {workspace_id}")
    owner, repo = workspace_id.split("-", 1)
    manager = WorkspaceManager()
    workspace = manager.get(owner, repo)
    if workspace is None:
        raise ValueError(f"Workspace '{workspace_id}' not found.")
    return workspace.source_dir


def _scan_files_impl(
    patterns: List[str],
    workspace_id: str,
    max_results: int = 50,
) -> Dict[str, Any]:
    """Core implementation for scan_files."""
    source_dir = _get_source_dir(workspace_id)
    if not source_dir.exists():
        raise ValueError(f"Source directory not found: {source_dir}")

    found_files: List[Dict[str, Any]] = []
    seen_paths: set[str] = set()

    for pattern in patterns:
        # Use recursive glob
        for path in source_dir.rglob(pattern):
            # Skip directories
            if path.is_dir():
                continue

            # Skip ignored directories
            parts = path.relative_to(source_dir).parts
            if any(part in _IGNORE_DIRS for part in parts):
                continue

            rel_path = str(path.relative_to(source_dir))
            if rel_path in seen_paths:
                continue
            seen_paths.add(rel_path)

            # Get file info
            try:
                stat = path.stat()
                size_kb = stat.st_size / 1024
                if size_kb >= 1024:
                    size_str = f"{size_kb / 1024:.1f} MB"
                else:
                    size_str = f"{size_kb:.1f} KB"
            except OSError:
                size_str = "unknown"

            found_files.append({
                "path": rel_path,
                "size": size_str,
                "pattern": pattern,
            })

            if len(found_files) >= max_results:
                break

        if len(found_files) >= max_results:
            break

    return {
        "files": found_files,
        "count": len(found_files),
        "patterns": patterns,
        "truncated": len(found_files) >= max_results,
    }


def build_scan_files_tool(workspace_id: str, database_url: str | None = None) -> BaseTool:
    """Create a scan_files tool bound to a specific workspace."""

    @tool(args_schema=ScanFilesInput)
    def scan_files(patterns: List[str], max_results: int = 50) -> Dict[str, Any]:
        """Scan codebase for files matching specific patterns.

        Use this to discover:
        - Heavy Assets (AI/ML models): ['*.onnx', '*.pt', '*.pth', '*.bin', '*.pkl', '*.weights']
        - Infrastructure & Config: ['Dockerfile', 'docker-compose.yml', '*.yaml', '*.toml', '.env*']
        - Native Extensions: ['*.so', '*.pyd', '*.c', '*.cpp', '*.cu', '*.h']
        - Web/Frontend: ['package.json', '*.ts', '*.tsx']

        These assets are NOT visible in the Python Call Graph.
        """
        return _scan_files_impl(patterns, workspace_id, max_results)

    return scan_files


__all__ = ["ScanFilesInput", "build_scan_files_tool"]
