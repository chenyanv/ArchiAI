"""Tool to extract a subgraph from an anchor node with node summaries."""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import select

from structural_scaffolding.database import ProfileRecord, create_session

from .graph_queries import get_graph, normalise_category

DEFAULT_MAX_DEPTH = 2
DEFAULT_MAX_NODES = 30


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
    """Implementation of subgraph extraction."""
    graph = get_graph(workspace_id, database_url)
    if anchor_node_id not in graph:
        raise ValueError(f"Node '{anchor_node_id}' does not exist in the call graph.")

    node_ids, edges = _bfs_expand(graph, anchor_node_id, max_depth, max_nodes)
    summaries = _load_node_summaries(node_ids, workspace_id, database_url, include_source)

    return _build_subgraph_payload(graph, anchor_node_id, node_ids, edges, summaries)


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
