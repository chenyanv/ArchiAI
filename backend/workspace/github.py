"""GitHub URL parsing and tarball download utilities."""

from __future__ import annotations

import re
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from urllib.request import urlopen
from urllib.error import HTTPError, URLError


class GitHubError(Exception):
    """Base exception for GitHub operations."""


class InvalidGitHubURL(GitHubError):
    """Raised when a GitHub URL cannot be parsed."""


class DownloadError(GitHubError):
    """Raised when tarball download fails."""


# Patterns to match GitHub URLs
GITHUB_PATTERNS = [
    # https://github.com/owner/repo
    re.compile(r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"),
    # https://github.com/owner/repo/tree/branch
    re.compile(r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/tree/(?P<branch>[^/]+)"),
    # git@github.com:owner/repo.git
    re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$"),
    # owner/repo shorthand
    re.compile(r"^(?P<owner>[^/]+)/(?P<repo>[^/]+)$"),
]


def parse_github_url(url: str) -> Tuple[str, str, Optional[str]]:
    """Parse a GitHub URL into (owner, repo, branch).

    Args:
        url: GitHub URL in various formats

    Returns:
        Tuple of (owner, repo, branch). Branch is None if not specified.

    Raises:
        InvalidGitHubURL: If the URL cannot be parsed
    """
    url = url.strip()

    for pattern in GITHUB_PATTERNS:
        match = pattern.match(url)
        if match:
            groups = match.groupdict()
            owner = groups["owner"]
            repo = groups["repo"].removesuffix(".git")
            branch = groups.get("branch")
            return owner, repo, branch

    raise InvalidGitHubURL(f"Cannot parse GitHub URL: {url}")


def get_tarball_url(owner: str, repo: str, branch: Optional[str] = None) -> str:
    """Get the tarball download URL for a GitHub repository.

    Args:
        owner: Repository owner
        repo: Repository name
        branch: Branch name (defaults to HEAD/main)

    Returns:
        Tarball download URL
    """
    ref = branch or "HEAD"
    return f"https://github.com/{owner}/{repo}/archive/{ref}.tar.gz"


def download_tarball(
    owner: str,
    repo: str,
    dest: Path,
    branch: Optional[str] = None,
) -> Path:
    """Download and extract a GitHub repository tarball.

    Args:
        owner: Repository owner
        repo: Repository name
        dest: Destination directory (will contain extracted files)
        branch: Branch name (defaults to HEAD/main)

    Returns:
        Path to the extracted source directory

    Raises:
        DownloadError: If download or extraction fails
    """
    url = get_tarball_url(owner, repo, branch)

    # Create destination if needed
    dest.mkdir(parents=True, exist_ok=True)
    source_dir = dest / "source"

    # Skip if already downloaded
    if source_dir.exists() and any(source_dir.iterdir()):
        return source_dir

    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = Path(tmp.name)

            # Download tarball
            with urlopen(url, timeout=60) as response:
                shutil.copyfileobj(response, tmp)

        # Extract tarball
        with tarfile.open(tmp_path, "r:gz") as tar:
            # GitHub tarballs have a single root directory like "repo-branch/"
            members = tar.getmembers()
            if not members:
                raise DownloadError("Empty tarball")

            # Find the root directory name
            root_name = members[0].name.split("/")[0]

            # Extract to temp location
            extract_tmp = dest / "_extract_tmp"
            extract_tmp.mkdir(exist_ok=True)
            tar.extractall(extract_tmp)

            # Move contents to source/
            extracted_root = extract_tmp / root_name
            if extracted_root.exists():
                if source_dir.exists():
                    shutil.rmtree(source_dir)
                shutil.move(str(extracted_root), str(source_dir))

            # Cleanup
            shutil.rmtree(extract_tmp, ignore_errors=True)

        return source_dir

    except HTTPError as e:
        raise DownloadError(f"HTTP error downloading {url}: {e.code} {e.reason}")
    except URLError as e:
        raise DownloadError(f"Network error downloading {url}: {e.reason}")
    except tarfile.TarError as e:
        raise DownloadError(f"Error extracting tarball: {e}")
    finally:
        # Cleanup temp file
        if "tmp_path" in locals():
            tmp_path.unlink(missing_ok=True)


__all__ = [
    "GitHubError",
    "InvalidGitHubURL",
    "DownloadError",
    "parse_github_url",
    "get_tarball_url",
    "download_tarball",
]
