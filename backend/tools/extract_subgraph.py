"""Tool to extract a subgraph from an anchor node with node summaries."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import select

from structural_scaffolding.database import ProfileRecord, create_session

from .graph_queries import get_graph, normalise_category

DEFAULT_MAX_DEPTH = 2
DEFAULT_MAX_NODES = 30


@dataclass(frozen=True)
class ParsedNodeId:
    """Parse and identify node ID structure and type."""

    language: str
    file_path: str
    class_name: Optional[str] = None
    method_name: Optional[str] = None

    @classmethod
    def parse(cls, node_id: str) -> ParsedNodeId:
        """
        Parse node_id into components.

        Format:
        - file: python::path/to/file.py
        - class: python::path/to/file.py::ClassName
        - method: python::path/to/file.py::ClassName::method_name
        - function: python::path/to/file.py::function_name (treated as class_name)

        Args:
            node_id: The node ID to parse

        Returns:
            ParsedNodeId with identified components
        """
        if not node_id.startswith("python::"):
            raise ValueError(f"Invalid node_id format: {node_id}. Must start with 'python::'")

        parts = node_id[8:].split("::")  # Remove "python::" prefix

        if len(parts) == 1:
            # File level only
            return cls(language="python", file_path=parts[0])

        file_path = parts[0]

        if len(parts) == 2:
            # Class or function level
            return cls(language="python", file_path=file_path, class_name=parts[1])

        if len(parts) >= 3:
            # Method level: class_name::method_name
            return cls(
                language="python",
                file_path=file_path,
                class_name=parts[1],
                method_name=parts[2],
            )

        raise ValueError(f"Invalid node_id format: {node_id}")

    def to_node_id(self) -> str:
        """Convert back to node_id string format."""
        parts = [self.language, self.file_path]
        if self.class_name:
            parts.append(self.class_name)
        if self.method_name:
            parts.append(self.method_name)
        return "::".join(parts)

    def to_class_node_id(self) -> str:
        """Get the class-level node_id (for graph lookup)."""
        if not self.class_name:
            return self.to_node_id()
        return f"{self.language}::{self.file_path}::{self.class_name}"

    def is_method(self) -> bool:
        """Check if this is a method-level node_id."""
        return self.method_name is not None


class ExtractSubgraphInput(BaseModel):
    anchor_node_id: str = Field(..., min_length=1, description="The node ID to start expansion from.")
    max_depth: int = Field(
        default=DEFAULT_MAX_DEPTH,
        ge=1,
        le=5,
        description="Maximum BFS depth from the anchor node.",
    )
    max_nodes: int = Field(
        default=DEFAULT_MAX_NODES,
        ge=5,
        le=100,
        description="Maximum number of nodes to include in the subgraph.",
    )
    include_source: bool = Field(
        default=False,
        description="Whether to include source code snippets (first 500 chars) for each node.",
    )

# TODO: 是不是做dfs对内存更好。。。
def _bfs_expand(
    graph: nx.MultiDiGraph,
    anchor: str,
    max_depth: int,
    max_nodes: int,
) -> Tuple[Set[str], List[Tuple[str, str, str]]]:
    """BFS expand from anchor node, collecting nodes and edges."""
    if anchor not in graph:
        return set(), []

    visited: Set[str] = {anchor}
    edges: List[Tuple[str, str, str]] = []
    queue: deque[Tuple[str, int]] = deque([(anchor, 0)])

    while queue and len(visited) < max_nodes:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue

        # Expand outgoing edges (calls)
        for neighbor in graph.successors(current):
            edge_data = graph.get_edge_data(current, neighbor) or {}
            for attrs in edge_data.values() if graph.is_multigraph() else [edge_data]:
                edge_type = attrs.get("type", "CALLS")
                if (current, neighbor, edge_type) not in edges:
                    edges.append((current, neighbor, edge_type))

            if neighbor not in visited and len(visited) < max_nodes:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))

        # Expand incoming edges (called_by)
        for neighbor in graph.predecessors(current):
            edge_data = graph.get_edge_data(neighbor, current) or {}
            for attrs in edge_data.values() if graph.is_multigraph() else [edge_data]:
                edge_type = attrs.get("type", "CALLS")
                if (neighbor, current, edge_type) not in edges:
                    edges.append((neighbor, current, edge_type))

            if neighbor not in visited and len(visited) < max_nodes:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))

    return visited, edges


def _get_method_source(
    node_id: str, workspace_id: str, database_url: str | None
) -> Optional[Dict[str, Any]]:
    """
    Retrieve method-level source code from database.

    Fallback strategy when node is not found in call graph but exists in database.

    Args:
        node_id: Full node ID (including method name)
        workspace_id: Workspace identifier
        database_url: Database URL

    Returns:
        Dict with source_code, docstring, line ranges, or None if not found
    """
    session = create_session(database_url)
    try:
        stmt = select(ProfileRecord).where(
            ProfileRecord.id == node_id,
            ProfileRecord.workspace_id == workspace_id,
            ProfileRecord.kind == "method",
        )
        record = session.execute(stmt).scalar_one_or_none()

        if not record:
            return None

        return {
            "source_code": record.source_code or "",
            "docstring": record.docstring or "",
            "start_line": record.start_line,
            "end_line": record.end_line,
            "parameters": record.parameters,
            "kind": record.kind,
        }
    finally:
        session.close()


def _generate_fallback_summary(record: ProfileRecord) -> str:
    """Generate a summary when docstring is not available.

    Uses function signature, class name, and file path context.
    """
    parts: List[str] = []

    # Use class.function or just function name
    if record.class_name and record.function_name:
        parts.append(f"{record.class_name}.{record.function_name}")
    elif record.function_name:
        parts.append(record.function_name)
    elif record.class_name:
        parts.append(f"class {record.class_name}")

    # Add parameter hints if available
    if record.parameters:
        param_names = [p.get("name", p) if isinstance(p, dict) else str(p) for p in record.parameters[:5]]
        if param_names:
            parts.append(f"params: {', '.join(param_names)}")

    # Add file context
    if record.file_path:
        # Extract meaningful path segments
        path_parts = record.file_path.replace("\\", "/").split("/")
        # Take last 2-3 meaningful segments
        meaningful = [p for p in path_parts if p and not p.startswith(".")][-3:]
        if meaningful:
            parts.append(f"in {'/'.join(meaningful)}")

    return " | ".join(parts) if parts else f"{record.kind} at line {record.start_line}"


def _load_node_summaries(
    node_ids: Set[str],
    workspace_id: str,
    database_url: str | None,
    include_source: bool,
) -> Dict[str, Dict[str, Any]]:
    """Load docstrings and metadata from ProfileRecord for each node."""
    session = create_session(database_url)
    try:
        stmt = select(ProfileRecord).where(
            ProfileRecord.workspace_id == workspace_id,
            ProfileRecord.id.in_(node_ids),
        )
        records = session.execute(stmt).scalars().all()

        summaries: Dict[str, Dict[str, Any]] = {}
        for record in records:
            summary: Dict[str, Any] = {
                "kind": record.kind,
                "file_path": record.file_path,
                "function_name": record.function_name,
                "class_name": record.class_name,
                "start_line": record.start_line,
                "end_line": record.end_line,
            }

            # Use docstring if available, otherwise generate fallback
            if record.docstring and record.docstring.strip():
                doc = record.docstring.strip()
                summary["docstring"] = doc[:300] + "..." if len(doc) > 300 else doc
            else:
                summary["inferred_summary"] = _generate_fallback_summary(record)

            if include_source and record.source_code:
                # Truncate source to first 500 chars
                src = record.source_code.strip()
                summary["source_snippet"] = src[:500] + "..." if len(src) > 500 else src

            if record.parameters:
                summary["parameters"] = record.parameters

            summaries[record.id] = summary

        return summaries
    finally:
        session.close()


def _build_subgraph_payload(
    graph: nx.MultiDiGraph,
    anchor: str,
    node_ids: Set[str],
    edges: List[Tuple[str, str, str]],
    summaries: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the final payload with nodes, edges, and summaries."""
    nodes: List[Dict[str, Any]] = []
    for node_id in sorted(node_ids):
        attrs = graph.nodes.get(node_id, {})
        node_payload: Dict[str, Any] = {
            "id": node_id,
            "label": attrs.get("label"),
            "kind": attrs.get("kind"),
            "category": normalise_category(attrs),
            "is_anchor": node_id == anchor,
        }

        # Merge summary from ProfileRecord
        if node_id in summaries:
            summary = summaries[node_id]
            node_payload["file_path"] = summary.get("file_path")
            node_payload["function_name"] = summary.get("function_name")
            node_payload["class_name"] = summary.get("class_name")
            node_payload["line_range"] = f"{summary.get('start_line')}-{summary.get('end_line')}"
            node_payload["has_source"] = True  # Can use get_source_code on this node

            # Include either docstring or inferred summary
            if "docstring" in summary:
                node_payload["summary"] = summary["docstring"]
                node_payload["summary_source"] = "docstring"
            elif "inferred_summary" in summary:
                node_payload["summary"] = summary["inferred_summary"]
                node_payload["summary_source"] = "inferred"

            if "source_snippet" in summary:
                node_payload["source_snippet"] = summary["source_snippet"]
            if "parameters" in summary:
                node_payload["parameters"] = summary["parameters"]
        else:
            node_payload["file_path"] = attrs.get("file_path")
            node_payload["summary"] = f"{attrs.get('kind', 'unknown')} node (no profile record)"
            node_payload["summary_source"] = "graph_only"
            node_payload["has_source"] = False  # Cannot use get_source_code - no profile record

        nodes.append(node_payload)

    edge_payloads: List[Dict[str, str]] = [
        {"source": src, "target": tgt, "type": edge_type}
        for src, tgt, edge_type in edges
    ]

    return {
        "anchor": anchor,
        "node_count": len(nodes),
        "edge_count": len(edge_payloads),
        "nodes": nodes,
        "edges": edge_payloads,
    }


def _extract_subgraph_impl(
    anchor_node_id: str,
    max_depth: int,
    max_nodes: int,
    include_source: bool,
    workspace_id: str,
    database_url: str | None,
) -> Dict[str, Any]:
    """
    Implementation of subgraph extraction with intelligent fallback strategy.

    Three-tier approach:
    1️⃣ Try to find node in call graph → return call relationships + BFS expansion
    2️⃣ If method not in graph → retrieve source code from database
    3️⃣ If method's class is in graph → return class context with note
    """
    graph = get_graph(workspace_id, database_url)
    parsed = ParsedNodeId.parse(anchor_node_id)

    # STRATEGY 1️⃣: Direct lookup in call graph
    if anchor_node_id in graph:
        # Standard path: node is in graph, perform BFS expansion
        node_ids, edges = _bfs_expand(graph, anchor_node_id, max_depth, max_nodes)
        summaries = _load_node_summaries(node_ids, workspace_id, database_url, include_source)
        return _build_subgraph_payload(graph, anchor_node_id, node_ids, edges, summaries)

    # STRATEGY 2️⃣: Fallback for method nodes not in graph
    if parsed.is_method():
        # Try to retrieve method source code from database
        method_source = _get_method_source(anchor_node_id, workspace_id, database_url)

        if method_source:
            # ✅ Found method in database → return its source code
            node_payload = {
                "id": anchor_node_id,
                "title": parsed.method_name,
                "kind": "method",
                "category": "method",
                "file_path": parsed.file_path,
                "class_name": parsed.class_name,
                "line_range": f"{method_source['start_line']}-{method_source['end_line']}",
                "has_source": True,
                "summary": method_source["docstring"] or f"Method {parsed.method_name}",
                "summary_source": "docstring" if method_source["docstring"] else "inferred",
            }

            if method_source["source_code"] and include_source:
                src = method_source["source_code"].strip()
                node_payload["source_snippet"] = src[:500] + "..." if len(src) > 500 else src

            if method_source["parameters"]:
                node_payload["parameters"] = method_source["parameters"]

            return {
                "anchor": anchor_node_id,
                "node_count": 1,
                "edge_count": 0,
                "nodes": [node_payload],
                "edges": [],
                "note": f"Method source code retrieved from database (not in call graph)",
            }

        # STRATEGY 3️⃣: Method not found, try to get class context
        if parsed.class_name:
            class_node_id = parsed.to_class_node_id()

            if class_node_id in graph:
                # Found the class → return its context with explanatory note
                node_ids, edges = _bfs_expand(graph, class_node_id, max_depth, max_nodes)
                summaries = _load_node_summaries(node_ids, workspace_id, database_url, include_source)
                payload = _build_subgraph_payload(graph, class_node_id, node_ids, edges, summaries)
                payload["note"] = (
                    f"Method '{parsed.method_name}' not found in call graph. "
                    f"Showing class '{parsed.class_name}' context instead."
                )
                return payload

    # All strategies failed
    raise ValueError(
        f"Node '{anchor_node_id}' not found in call graph or database. "
        f"Cannot extract subgraph."
    )


def build_extract_subgraph_tool(workspace_id: str, database_url: str | None = None) -> BaseTool:
    """Create an extract_subgraph tool bound to a specific workspace."""

    @tool(args_schema=ExtractSubgraphInput)
    def extract_subgraph(
        anchor_node_id: str,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_nodes: int = DEFAULT_MAX_NODES,
        include_source: bool = False,
    ) -> Dict[str, Any]:
        """Extract a subgraph from an anchor node with BFS expansion.

        Returns nodes with summaries (docstring or inferred from function signature).
        Use this to understand the context around a specific function, class, or module.
        """
        return _extract_subgraph_impl(
            anchor_node_id, max_depth, max_nodes, include_source, workspace_id, database_url
        )

    return extract_subgraph


__all__ = ["ExtractSubgraphInput", "build_extract_subgraph_tool"]
