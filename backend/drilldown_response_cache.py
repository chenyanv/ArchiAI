"""File-system based cache for ComponentDrilldownResponse objects.

Mimics orchestration's plan caching strategy but with breadcrumb-based keys for drilldown states.
Cache structure:
  {workspace.results_dir}/drilldown/
  ├── {component_id}/
  │   ├── {breadcrumb_hash}/response.json
  │   ├── {breadcrumb_hash_2}/response.json
  │   └── metadata.json (tracks timestamps)
  └── {component_id_2}/...
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from backend.component_agent.schemas import (
        ComponentDrilldownResponse,
        NavigationBreadcrumb,
    )


class DrilldownResponseCache:
    """File-system based cache for drilldown responses with TTL and metadata tracking."""

    TTL_SECONDS = 86400 * 7  # 7 days
    METADATA_FILE = "metadata.json"

    @staticmethod
    def _get_breadcrumb_hash(breadcrumbs: list[NavigationBreadcrumb]) -> str:
        """Generate deterministic hash from breadcrumb path.

        Args:
            breadcrumbs: List of NavigationBreadcrumb objects

        Returns:
            12-character hex hash of canonical breadcrumb path
        """
        if not breadcrumbs:
            return "root"

        breadcrumb_keys = [b.node_key for b in breadcrumbs]
        canonical = "→".join(breadcrumb_keys)
        return hashlib.md5(canonical.encode()).hexdigest()[:12]

    @staticmethod
    def _ensure_cache_dir(cache_dir: Path) -> None:
        """Create cache directory if it doesn't exist.

        Args:
            cache_dir: Path to cache directory
        """
        cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get(
        cls,
        workspace_results_dir: Path,
        component_id: str,
        breadcrumbs: list[NavigationBreadcrumb],
        check_ttl: bool = True,
    ) -> Optional[dict]:
        """Retrieve cached drilldown response if exists and valid.

        Args:
            workspace_results_dir: Base results directory for workspace
            component_id: Component identifier (e.g., 'python::api/routes.py::RequestHandler')
            breadcrumbs: Current breadcrumb navigation path
            check_ttl: Whether to validate cache TTL

        Returns:
            Cached response dict or None if not found/expired
        """
        breadcrumb_hash = cls._get_breadcrumb_hash(breadcrumbs)
        cache_file = (
            Path(workspace_results_dir)
            / "drilldown"
            / component_id
            / breadcrumb_hash
            / "response.json"
        )

        if not cache_file.exists():
            return None

        try:
            # Check TTL if requested
            if check_ttl:
                metadata = cls._load_metadata(
                    Path(workspace_results_dir) / "drilldown" / component_id
                )
                if metadata:
                    last_updated = metadata.get("drilldown", {}).get(
                        breadcrumb_hash, {}
                    ).get("last_updated")
                    if last_updated:
                        last_updated_dt = datetime.fromisoformat(last_updated)
                        if (datetime.now() - last_updated_dt) > timedelta(
                            seconds=cls.TTL_SECONDS
                        ):
                            # Cache expired, delete it
                            cache_file.unlink()
                            return None

            # Load and return cached response
            with open(cache_file, "r") as f:
                return json.load(f)

        except (json.JSONDecodeError, IOError) as e:
            # If cache is corrupted, silently return None
            print(f"Warning: Failed to load cache from {cache_file}: {e}")
            return None

    @classmethod
    def save(
        cls,
        workspace_results_dir: Path,
        component_id: str,
        breadcrumbs: list[NavigationBreadcrumb],
        response: dict,
    ) -> None:
        """Save drilldown response to cache.

        Args:
            workspace_results_dir: Base results directory for workspace
            component_id: Component identifier
            breadcrumbs: Current breadcrumb navigation path
            response: ComponentDrilldownResponse as dict
        """
        breadcrumb_hash = cls._get_breadcrumb_hash(breadcrumbs)
        component_cache_dir = (
            Path(workspace_results_dir) / "drilldown" / component_id / breadcrumb_hash
        )

        # Create directory structure
        cls._ensure_cache_dir(component_cache_dir)

        # Save response
        response_file = component_cache_dir / "response.json"
        try:
            with open(response_file, "w") as f:
                json.dump(response, f, indent=2)
        except IOError as e:
            print(f"Warning: Failed to save cache to {response_file}: {e}")
            return

        # Update metadata
        cls._update_metadata(
            Path(workspace_results_dir) / "drilldown" / component_id,
            breadcrumb_hash,
        )

    @staticmethod
    def _load_metadata(component_cache_dir: Path) -> Optional[dict]:
        """Load metadata file for a component.

        Args:
            component_cache_dir: Path to component's cache directory

        Returns:
            Metadata dict or None if not found
        """
        metadata_file = component_cache_dir / DrilldownResponseCache.METADATA_FILE

        if not metadata_file.exists():
            return None

        try:
            with open(metadata_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    @staticmethod
    def _update_metadata(component_cache_dir: Path, breadcrumb_hash: str) -> None:
        """Update metadata file for a component.

        Args:
            component_cache_dir: Path to component's cache directory
            breadcrumb_hash: Hash of the breadcrumb being cached
        """
        metadata_file = component_cache_dir / DrilldownResponseCache.METADATA_FILE

        # Load existing or create new
        metadata = {"drilldown": {}} if not metadata_file.exists() else {}
        if metadata_file.exists():
            try:
                with open(metadata_file, "r") as f:
                    metadata = json.load(f)
            except (json.JSONDecodeError, IOError):
                metadata = {"drilldown": {}}

        # Update timestamp for this breadcrumb
        if "drilldown" not in metadata:
            metadata["drilldown"] = {}

        metadata["drilldown"][breadcrumb_hash] = {
            "last_updated": datetime.now().isoformat(),
            "ttl_seconds": DrilldownResponseCache.TTL_SECONDS,
        }

        # Save updated metadata
        try:
            DrilldownResponseCache._ensure_cache_dir(component_cache_dir)
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)
        except IOError as e:
            print(f"Warning: Failed to save metadata to {metadata_file}: {e}")

    @classmethod
    def clear_breadcrumb(
        cls,
        workspace_results_dir: Path,
        component_id: str,
        breadcrumbs: list[NavigationBreadcrumb],
    ) -> None:
        """Clear cache for specific breadcrumb path.

        Args:
            workspace_results_dir: Base results directory for workspace
            component_id: Component identifier
            breadcrumbs: Breadcrumb path to clear
        """
        breadcrumb_hash = cls._get_breadcrumb_hash(breadcrumbs)
        cache_dir = (
            Path(workspace_results_dir) / "drilldown" / component_id / breadcrumb_hash
        )

        if cache_dir.exists():
            import shutil

            shutil.rmtree(cache_dir)

    @classmethod
    def clear_component(
        cls, workspace_results_dir: Path, component_id: str
    ) -> None:
        """Clear all cache for a specific component.

        Args:
            workspace_results_dir: Base results directory for workspace
            component_id: Component identifier
        """
        component_cache_dir = Path(workspace_results_dir) / "drilldown" / component_id

        if component_cache_dir.exists():
            import shutil

            shutil.rmtree(component_cache_dir)

    @classmethod
    def clear_expired(cls, workspace_results_dir: Path) -> int:
        """Clear all expired cache entries across all components.

        Args:
            workspace_results_dir: Base results directory for workspace

        Returns:
            Number of expired entries removed
        """
        drilldown_dir = Path(workspace_results_dir) / "drilldown"
        if not drilldown_dir.exists():
            return 0

        removed_count = 0

        # Iterate through all components
        for component_dir in drilldown_dir.iterdir():
            if not component_dir.is_dir():
                continue

            metadata = cls._load_metadata(component_dir)
            if not metadata or "drilldown" not in metadata:
                continue

            # Check each breadcrumb entry
            expired_hashes = []
            for breadcrumb_hash, info in metadata["drilldown"].items():
                last_updated = info.get("last_updated")
                if last_updated:
                    last_updated_dt = datetime.fromisoformat(last_updated)
                    if (datetime.now() - last_updated_dt) > timedelta(
                        seconds=cls.TTL_SECONDS
                    ):
                        expired_hashes.append(breadcrumb_hash)

            # Remove expired entries
            for breadcrumb_hash in expired_hashes:
                cache_dir = component_dir / breadcrumb_hash
                if cache_dir.exists():
                    import shutil

                    shutil.rmtree(cache_dir)
                    removed_count += 1

                # Update metadata
                del metadata["drilldown"][breadcrumb_hash]

            # Save updated metadata
            if expired_hashes:
                try:
                    with open(component_dir / cls.METADATA_FILE, "w") as f:
                        json.dump(metadata, f, indent=2)
                except IOError:
                    pass

        return removed_count


__all__ = ["DrilldownResponseCache"]
