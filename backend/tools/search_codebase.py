"""Tool to search for string patterns in codebase files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Directories to ignore during searching
_IGNORE_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    ".idea", "dist", "build", ".egg-info", ".tox", ".pytest_cache",
    ".mypy_cache", ".ruff_cache",
})

# Text file extensions to search
_TEXT_EXTENSIONS = frozenset({
    ".py", ".md", ".yaml", ".yml", ".json", ".txt", ".sh",
    ".ini", ".toml", ".js", ".ts", ".tsx", ".jsx", ".css",
    ".html", ".xml", ".cfg", ".conf", ".env", ".dockerfile",
})

# Files without extension that are text
_TEXT_FILENAMES = frozenset({
    "Dockerfile", "Makefile", "README", "LICENSE", "CHANGELOG",
    ".gitignore", ".dockerignore", ".env",
})

# Maximum matches to prevent context overflow
_MAX_MATCHES = 30


class SearchCodebaseInput(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description=(
            "String or regex pattern to search for. Be precise to avoid too many results. "
            "E.g., 'import xgboost', 'class .*Parser', 'model.onnx', '@app.route'."
        ),
    )
    context_lines: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Number of lines of context before and after each match. Default is 2.",
    )
    file_pattern: Optional[str] = Field(
        default=None,
        description="Optional glob pattern to filter files. E.g., '*.py' to search only Python files.",
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


def _is_text_file(path: Path) -> bool:
    """Check if a file is likely a text file."""
    if path.name in _TEXT_FILENAMES:
        return True
    return path.suffix.lower() in _TEXT_EXTENSIONS


def _search_codebase_impl(
    query: str,
    workspace_id: str,
    context_lines: int = 2,
    file_pattern: Optional[str] = None,
) -> Dict[str, Any]:
    """Core implementation for search_codebase."""
    source_dir = _get_source_dir(workspace_id)
    if not source_dir.exists():
        raise ValueError(f"Source directory not found: {source_dir}")

    # Compile regex pattern
    try:
        pattern = re.compile(query)
    except re.error:
        # Fallback to literal string search
        pattern = re.compile(re.escape(query))

    results: List[Dict[str, Any]] = []
    match_count = 0

    # Get files to search
    if file_pattern:
        files = list(source_dir.rglob(file_pattern))
    else:
        files = list(source_dir.rglob("*"))

    for filepath in files:
        if not filepath.is_file():
            continue

        # Skip ignored directories
        parts = filepath.relative_to(source_dir).parts
        if any(part in _IGNORE_DIRS for part in parts):
            continue

        # Skip non-text files
        if not _is_text_file(filepath):
            continue

        rel_path = str(filepath.relative_to(source_dir))

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except (OSError, IOError):
            continue

        for i, line in enumerate(lines):
            if pattern.search(line):
                match_count += 1

                # Extract context
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)

                snippet_lines = []
                for j in range(start, end):
                    prefix = ">>>" if j == i else "   "
                    line_content = lines[j].rstrip()
                    snippet_lines.append(f"{j + 1:4d} {prefix} {line_content}")

                results.append({
                    "file": rel_path,
                    "line": i + 1,
                    "snippet": "\n".join(snippet_lines),
                })

                if match_count >= _MAX_MATCHES:
                    break

        if match_count >= _MAX_MATCHES:
            break

    if not results:
        return {
            "matches": [],
            "count": 0,
            "query": query,
            "message": f"No matches found for '{query}'.",
        }

    return {
        "matches": results,
        "count": len(results),
        "query": query,
        "truncated": match_count >= _MAX_MATCHES,
    }


def build_search_codebase_tool(workspace_id: str, database_url: str | None = None) -> BaseTool:
    """Create a search_codebase tool bound to a specific workspace."""

    @tool(args_schema=SearchCodebaseInput)
    def search_codebase(
        query: str,
        context_lines: int = 2,
        file_pattern: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search for string or regex patterns in codebase files.

        Use this to find dynamic logic that static analysis misses:
        - Asset Loading: Search for filenames found by scan_files (e.g., 'model.onnx')
        - Dynamic Imports: Search for 'importlib', '__import__', 'sys.modules'
        - Registries/Plugins: Search for '@register', '@app.route', '@task'
        - Configuration: Search for 'os.getenv', 'config.get'
        - Entry Points: Search for "if __name__ == '__main__'"

        Returns matching lines with surrounding context.
        """
        return _search_codebase_impl(query, workspace_id, context_lines, file_pattern)

    return search_codebase


__all__ = ["SearchCodebaseInput", "build_search_codebase_tool"]
