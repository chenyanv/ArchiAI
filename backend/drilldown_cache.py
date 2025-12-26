"""Breadcrumb caching for drilldown context."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional

import redis

# Redis client (can be configured via REDIS_URL env or defaults to localhost)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

BREADCRUMB_CACHE_TTL = 3600  # 1 hour


class BreadcrumbCache:
    """Manage breadcrumb state caching for drilldown navigation."""

    @staticmethod
    def save_breadcrumbs(workspace_id: str, breadcrumbs: List[Dict[str, Any]]) -> str:
        """Save breadcrumbs to cache, return cache_id.

        Args:
            workspace_id: Workspace identifier
            breadcrumbs: List of breadcrumb dictionaries

        Returns:
            cache_id: Unique identifier for this breadcrumb state
        """
        cache_id = f"breadcrumbs_{uuid.uuid4().hex[:12]}"
        key = f"drilldown:breadcrumbs:{workspace_id}:{cache_id}"

        # Serialize and store with TTL
        redis_client.setex(
            key,
            BREADCRUMB_CACHE_TTL,
            json.dumps(breadcrumbs),
        )

        return cache_id

    @staticmethod
    def load_breadcrumbs(workspace_id: str, cache_id: str) -> Optional[List[Dict[str, Any]]]:
        """Load breadcrumbs from cache.

        Args:
            workspace_id: Workspace identifier
            cache_id: Cache identifier (returned from save_breadcrumbs)

        Returns:
            Breadcrumbs list if found and not expired, None otherwise
        """
        key = f"drilldown:breadcrumbs:{workspace_id}:{cache_id}"
        data = redis_client.get(key)

        if not data:
            return None

        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def add_breadcrumb(
        workspace_id: str,
        cache_id: str,
        node: Dict[str, Any]
    ) -> str:
        """Add a node to existing breadcrumbs, return new cache_id.

        Args:
            workspace_id: Workspace identifier
            cache_id: Existing cache identifier
            node: Node dictionary to append

        Returns:
            New cache_id with the added breadcrumb
        """
        # Load existing breadcrumbs
        breadcrumbs = BreadcrumbCache.load_breadcrumbs(workspace_id, cache_id)
        if breadcrumbs is None:
            raise ValueError(f"Cache {cache_id} not found or expired")

        # Append new breadcrumb
        new_breadcrumb = {
            "node_key": node.get("node_key"),
            "title": node.get("title"),
            "node_type": node.get("node_type"),
            "target_id": node.get("target_id"),
        }
        if node.get("action_parameters"):
            new_breadcrumb["metadata"] = {"action_parameters": node.get("action_parameters")}

        new_breadcrumbs = breadcrumbs + [new_breadcrumb]

        # Save new state and return new cache_id
        return BreadcrumbCache.save_breadcrumbs(workspace_id, new_breadcrumbs)

    @staticmethod
    def cleanup(workspace_id: str, cache_id: str) -> None:
        """Explicitly delete a breadcrumb cache (optional).

        Args:
            workspace_id: Workspace identifier
            cache_id: Cache identifier to delete
        """
        key = f"drilldown:breadcrumbs:{workspace_id}:{cache_id}"
        redis_client.delete(key)


__all__ = ["BreadcrumbCache"]
