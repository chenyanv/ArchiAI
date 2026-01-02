"""Tool to analyze inheritance patterns in the codebase."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import networkx as nx
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import select

from structural_scaffolding.database import ProfileRecord, create_session
from tools.graph_queries import get_graph, node_snapshot


class AnalyzeInheritanceGraphInput(BaseModel):
    """Input schema for inheritance graph analysis."""

    scope_path: str = Field(
        ...,
        min_length=1,
        description="Limit analysis to files containing this path (e.g., 'ragflow/deepdoc'). Required to avoid analyzing entire codebase.",
    )
    target_class_name: Optional[str] = Field(
        default=None,
        description="Specific class name to analyze inheritance for. If omitted, auto-discovers the most-inherited base class in scope.",
    )


def _find_classes_in_scope_from_db(
    workspace_id: str,
    database_url: str | None,
    scope_path: str
) -> List[str]:
    """Find all class ProfileRecords within the given scope.

    This queries ProfileRecord directly (not the CallGraph) to ensure
    we only return classes that have source code indexed in the database.
    This prevents returning nodes that exist in the CallGraph but have
    no source code available.
    """
    session = create_session(database_url)
    try:
        stmt = select(ProfileRecord).where(
            ProfileRecord.workspace_id == workspace_id,
            ProfileRecord.kind == "class",
            ProfileRecord.file_path.contains(scope_path),
        )
        records = session.execute(stmt).scalars().all()
        return [r.id for r in records]
    finally:
        session.close()


def _find_classes_in_scope(graph: nx.MultiDiGraph, scope_path: str) -> List[str]:
    """Find all class nodes within the given scope.

    DEPRECATED: Use _find_classes_in_scope_from_db instead to ensure
    we only return classes with source code available.
    """
    classes = []
    for node_id, attrs in graph.nodes(data=True):
        file_path = attrs.get("file_path", "")
        kind = attrs.get("kind", "")
        # Match if file_path contains scope_path and node is a class
        if scope_path in file_path and kind == "class":
            classes.append(node_id)
    return classes


def _find_base_class_candidates(graph: nx.MultiDiGraph, classes: List[str]) -> Dict[str, int]:
    """Count how many times each class is inherited from (in-degree of INHERITS_FROM edges).

    Returns a dict mapping class_id -> inheritance_count.
    """
    inheritance_count: Dict[str, int] = {}

    for node_id in classes:
        # Check if this class is inherited by others
        # (i.e., has incoming INHERITS_FROM edges)
        for predecessor in graph.predecessors(node_id):
            edge_data = graph.get_edge_data(predecessor, node_id) or {}
            for attrs in edge_data.values() if isinstance(edge_data, dict) else [edge_data]:
                if isinstance(attrs, dict) and attrs.get("type") == "INHERITS_FROM":
                    inheritance_count[node_id] = inheritance_count.get(node_id, 0) + 1

    return inheritance_count


def _get_implementations(graph: nx.MultiDiGraph, base_class_id: str, workspace_id: str | None = None, database_url: str | None = None) -> List[Dict[str, Any]]:
    """Find all classes that inherit from the given base class."""
    implementations = []

    # Find all predecessors (classes that inherit from base_class)
    # Note: INHERITS_FROM edges go ChildClass -> ParentClass, so we look at predecessors
    for predecessor in graph.predecessors(base_class_id):
        edge_data = graph.get_edge_data(predecessor, base_class_id) or {}

        # Check if there's an INHERITS_FROM edge
        for attrs in edge_data.values() if isinstance(edge_data, dict) else [edge_data]:
            if isinstance(attrs, dict) and attrs.get("type") == "INHERITS_FROM":
                implementations.append(node_snapshot(graph, predecessor, workspace_id, database_url))
                break

    return implementations


def _get_parents(graph: nx.MultiDiGraph, class_id: str, workspace_id: str | None = None, database_url: str | None = None) -> List[Dict[str, Any]]:
    """Find all parent classes of the given class."""
    parents = []

    # Find all successors (classes that this class inherits from)
    # Note: INHERITS_FROM edges go ChildClass -> ParentClass, so we look at successors
    for successor in graph.successors(class_id):
        edge_data = graph.get_edge_data(class_id, successor) or {}

        # Check if there's an INHERITS_FROM edge
        for attrs in edge_data.values() if isinstance(edge_data, dict) else [edge_data]:
            if isinstance(attrs, dict) and attrs.get("type") == "INHERITS_FROM":
                parents.append(node_snapshot(graph, successor, workspace_id, database_url))
                break

    return parents


def _analyze_inheritance_scope(
    workspace_id: str,
    database_url: str | None,
    scope_path: str,
    target_class_name: Optional[str],
) -> Dict[str, Any]:
    """Core analysis logic for inheritance patterns.

    KEY CHANGE: Now queries ProfileRecord directly to find classes in scope,
    rather than relying on CallGraph. This ensures all returned classes have
    source code indexed in the database, preventing 404 errors when frontend
    tries to fetch source code.
    """
    graph = get_graph(workspace_id, database_url)
    # Use database query to find classes - guarantees all have source code
    classes_in_scope = _find_classes_in_scope_from_db(workspace_id, database_url, scope_path)
    if classes_in_scope:
        print(f"[inheritance:classes_in_scope] Found {len(classes_in_scope)} classes: {classes_in_scope[:5]}", flush=True)

    if not classes_in_scope:
        return {
            "success": False,
            "error": f"No classes found in scope '{scope_path}'",
        }

    # If target class is specified, analyze it directly
    if target_class_name:
        target_id = None
        for class_id in classes_in_scope:
            if target_class_name in class_id:  # Match substring
                target_id = class_id
                break

        if not target_id:
            return {
                "success": False,
                "error": f"Class '{target_class_name}' not found in scope '{scope_path}'",
            }

        parents = _get_parents(graph, target_id, workspace_id, database_url)
        return {
            "success": True,
            "mode": "explicit",
            "target_class": node_snapshot(graph, target_id, workspace_id, database_url),
            "parents": parents,
            "children": _get_implementations(graph, target_id, workspace_id, database_url),
        }

    # Auto-discover: find the most-inherited base class
    inheritance_counts = _find_base_class_candidates(graph, classes_in_scope)

    if not inheritance_counts:
        return {
            "success": False,
            "error": f"No inheritance patterns found in scope '{scope_path}'",
        }

    dominant_base = max(inheritance_counts, key=inheritance_counts.get)
    count = inheritance_counts[dominant_base]

    implementations = _get_implementations(graph, dominant_base, workspace_id, database_url)
    print(f"[inheritance:implementations] Found {len(implementations)} implementations", flush=True)
    if implementations:
        for impl in implementations[:3]:
            impl_id = impl.get("id", "unknown")
            impl_label = impl.get("label", "unknown")
            print(f"  - {impl_label} -> id: {impl_id}", flush=True)

    return {
        "success": True,
        "mode": "auto-discover",
        "pattern_detected": "Plugin Architecture" if count >= 2 else "Class Hierarchy",
        "dominant_base_class": node_snapshot(graph, dominant_base, workspace_id, database_url),
        "inheritance_depth": count,
        "implementations": implementations,
        "parents": _get_parents(graph, dominant_base, workspace_id, database_url),
    }


def build_analyze_inheritance_graph_tool(
    workspace_id: str, database_url: str | None = None
) -> BaseTool:
    """Create the analyze_inheritance_graph tool for a workspace."""

    @tool(args_schema=AnalyzeInheritanceGraphInput)
    def analyze_inheritance_graph(
        scope_path: str, target_class_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Analyze inheritance patterns in a code scope.

        This tool queries the existing code knowledge graph to understand class hierarchies,
        which is useful for discovering plugin systems, strategy patterns, and polymorphic designs.

        In 'auto-discover' mode (when target_class_name is omitted), this tool automatically
        identifies the most-inherited base class in the scope, helping you find the central
        interface without having to know its name upfront.
        """
        return _analyze_inheritance_scope(
            workspace_id, database_url, scope_path, target_class_name
        )

    return analyze_inheritance_graph


__all__ = ["build_analyze_inheritance_graph_tool"]
