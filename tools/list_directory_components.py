"""Tool to discover code components grouped by directory structure."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from .call_graph_pagerank import _compute_pagerank
from .graph_queries import get_graph, normalise_category

DEFAULT_LIMIT = 20
DEFAULT_NODES_PER_DIR = 5
DEFAULT_DEPTH = 1
# TODO: 这里直接改的深一些似乎也可以


class ListDirectoryComponentsInput(BaseModel):
    limit: int = Field(
        default=DEFAULT_LIMIT,
        ge=1,
        le=100,
        description="Maximum number of directories to return.",
    )
    nodes_per_dir: int = Field(
        default=DEFAULT_NODES_PER_DIR,
        ge=1,
        le=20,
        description="Maximum number of top nodes to return per directory.",
    )
    depth: int = Field(
        default=DEFAULT_DEPTH,
        ge=1,
        le=5,
        description="Directory depth to group by (1 = top-level, 2 = second-level, etc). Applied AFTER stripping common prefix.",
    )


def _find_common_prefix(file_paths: Set[str]) -> Tuple[str, ...]:
    """Find the common directory prefix across all file paths."""
    if not file_paths:
        return ()

    paths_parts = []
    for fp in file_paths:
        path = PurePosixPath(fp.replace("\\", "/").lstrip("./"))
        paths_parts.append(path.parts[:-1])  # Exclude filename

    if not paths_parts:
        return ()

    # Find common prefix
    common = []
    for parts in zip(*paths_parts):
        if len(set(parts)) == 1:
            common.append(parts[0])
        else:
            break

    return tuple(common)


def _extract_directory_at_depth(file_path: str, depth: int, prefix_len: int = 0) -> Optional[str]:
    """Extract directory path at the specified depth, after stripping prefix."""
    if not file_path:
        return None
    path = PurePosixPath(file_path.replace("\\", "/").lstrip("./"))
    parts = path.parts

    # Skip the common prefix
    remaining = parts[prefix_len:]
    if len(remaining) <= depth:
        return None

    return "/".join(remaining[:depth])


def _group_nodes_by_directory(
    graph: nx.MultiDiGraph,
    scores: Dict[str, float],
    depth: int,
    prefix_len: int = 0,
) -> Dict[str, List[Tuple[str, float, Dict[str, Any]]]]:
    """Group nodes by their directory at the specified depth."""
    groups: Dict[str, List[Tuple[str, float, Dict[str, Any]]]] = defaultdict(list)

    for node_id, score in scores.items():
        attrs = graph.nodes.get(node_id, {})
        file_path = attrs.get("file_path")
        if not file_path:
            continue

        directory = _extract_directory_at_depth(file_path, depth, prefix_len)
        if not directory:
            continue

        groups[directory].append((node_id, score, attrs))

    return groups


def _rank_directories(
    groups: Dict[str, List[Tuple[str, float, Dict[str, Any]]]],
) -> List[Tuple[str, float, float]]:
    """Rank directories by average PageRank score (not aggregate, to avoid bias toward large dirs)."""
    dir_scores: List[Tuple[str, float, float]] = []
    for directory, nodes in groups.items():
        total_score = sum(score for _, score, _ in nodes)
        avg_score = total_score / len(nodes) if nodes else 0.0
        dir_scores.append((directory, avg_score, total_score))
    # Sort by average score (descending)
    return sorted(dir_scores, key=lambda x: x[1], reverse=True)


def _format_directory_component(
    directory: str,
    nodes: List[Tuple[str, float, Dict[str, Any]]],
    nodes_per_dir: int,
    avg_score: float,
    total_score: float,
) -> Dict[str, Any]:
    """Format a directory component with its top nodes."""
    sorted_nodes = sorted(nodes, key=lambda x: x[1], reverse=True)[:nodes_per_dir]

    top_nodes = []
    for node_id, score, attrs in sorted_nodes:
        top_nodes.append({
            "id": node_id,
            "score": round(score, 6),
            "label": attrs.get("label"),
            "kind": attrs.get("kind"),
            "category": normalise_category(attrs),
            "file_path": attrs.get("file_path"),
        })

    kinds = defaultdict(int)
    categories = defaultdict(int)
    for _, _, attrs in nodes:
        kind = attrs.get("kind")
        if kind:
            kinds[kind] += 1
        category = normalise_category(attrs)
        if category != "unknown":
            categories[category] += 1

    return {
        "directory": directory,
        "avg_score": round(avg_score, 6),
        "total_score": round(total_score, 6),
        "node_count": len(nodes),
        "kind_distribution": dict(kinds) if kinds else None,
        "category_distribution": dict(categories) if categories else None,
        "top_nodes": top_nodes,
    }


def build_list_directory_components_tool(workspace_id: str, database_url: str | None = None) -> BaseTool:
    """Create a tool that lists code components grouped by directory."""

    @tool(args_schema=ListDirectoryComponentsInput)
    def list_directory_components(
        limit: int = DEFAULT_LIMIT,
        nodes_per_dir: int = DEFAULT_NODES_PER_DIR,
        depth: int = DEFAULT_DEPTH,
    ) -> List[Dict[str, Any]]:
        """List code components grouped by directory structure, ranked by average importance.

        Returns directories with their top nodes based on PageRank scores.
        Automatically strips common path prefix (e.g., 'src/app/') so depth=1 returns meaningful directories.
        Ranked by average score per node to avoid bias toward large directories.
        """
        graph = get_graph(workspace_id, database_url)
        if graph.number_of_nodes() == 0:
            return []

        scores = _compute_pagerank(graph)
        if not scores:
            return []

        # Find common prefix across all file paths
        file_paths: Set[str] = set()
        for node_id in scores:
            attrs = graph.nodes.get(node_id, {})
            fp = attrs.get("file_path")
            if fp:
                file_paths.add(fp)

        common_prefix = _find_common_prefix(file_paths)
        prefix_len = len(common_prefix)

        groups = _group_nodes_by_directory(graph, scores, depth, prefix_len)
        if not groups:
            return []

        dir_rankings = _rank_directories(groups)

        result = []
        for directory, avg_score, total_score in dir_rankings[:limit]:
            nodes = groups[directory]
            component = _format_directory_component(directory, nodes, nodes_per_dir, avg_score, total_score)
            result.append(component)

        return result

    return list_directory_components


__all__ = ["ListDirectoryComponentsInput", "build_list_directory_components_tool"]
