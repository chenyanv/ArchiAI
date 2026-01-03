"""List probable API entry points by inspecting route decorators from ProfileRecord."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import select

from structural_scaffolding.database import ProfileRecord, create_session

HTTP_METHOD_DECORATORS: Tuple[str, ...] = ("get", "post", "put", "delete", "patch", "options", "head", "trace")
ROUTE_DECORATORS: Tuple[str, ...] = ("route", "api_route", "websocket")


class ListEntryPointInput(BaseModel):
    limit: int = Field(20, ge=1, le=200, description="Maximum number of entry points to return.")
    framework: Optional[str] = Field(None, description="Optional framework filter (e.g. fastapi, flask).")
    path_contains: Optional[str] = Field(None, description="Restrict results to routes containing this substring.")
    include_docstring: bool = Field(False, description="Whether to include a short docstring summary when available.")


@dataclass(frozen=True)
class _DecoratorInfo:
    route: str
    methods: Tuple[str, ...]
    framework: str
    decorator: str
    lineno: int


@dataclass(frozen=True)
class _EntryPointRecord:
    call_graph_id: Optional[str]
    class_name: Optional[str]
    function_name: str
    symbol: str
    qualified_name: str
    file_path: str
    line_number: int
    route: str
    methods: Tuple[str, ...]
    framework: str
    decorator: str
    docstring: Optional[str]


def _discover_entry_points(workspace_id: str, database_url: str | None) -> Tuple[_EntryPointRecord, ...]:
    """Discover entry points from ProfileRecord in database."""
    session = create_session(database_url)
    try:
        stmt = select(ProfileRecord).where(
            ProfileRecord.workspace_id == workspace_id,
            ProfileRecord.kind == "file",
            ProfileRecord.file_path.like("%.py"),
        )
        file_records = list(session.execute(stmt).scalars())

        func_stmt = select(ProfileRecord).where(
            ProfileRecord.workspace_id == workspace_id,
            ProfileRecord.kind.in_(["function", "method"]),
        )
        func_records = list(session.execute(func_stmt).scalars())
        function_lookup = _build_symbol_lookup(func_records)

        records: List[_EntryPointRecord] = []
        for file_record in file_records:
            if not file_record.source_code or "@" not in file_record.source_code:
                continue
            try:
                syntax_tree = ast.parse(file_record.source_code, filename=file_record.file_path)
            except SyntaxError:
                continue

            frameworks = _detect_frameworks(syntax_tree)
            for entry in _iter_entry_points(
                syntax_tree, file_path=file_record.file_path, frameworks=frameworks, symbol_lookup=function_lookup
            ):
                records.append(entry)

        records.sort(key=lambda e: (e.route, e.file_path, e.line_number))
        return tuple(records)
    finally:
        session.close()


def _build_symbol_lookup(records: Sequence[ProfileRecord]) -> Dict[Tuple[str, Optional[str], str], ProfileRecord]:
    lookup: Dict[Tuple[str, Optional[str], str], ProfileRecord] = {}
    for record in records:
        if not record.file_path or not record.function_name:
            continue
        key = (str(record.file_path), record.class_name, str(record.function_name))
        lookup[key] = record
    return lookup


def _detect_frameworks(tree: ast.AST) -> Iterable[str]:
    frameworks: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("fastapi"):
                    frameworks.add("fastapi")
                if alias.name.startswith("flask"):
                    frameworks.add("flask")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("fastapi"):
                frameworks.add("fastapi")
            if node.module.startswith("flask"):
                frameworks.add("flask")
    return frameworks


def _iter_entry_points(
    tree: ast.AST,
    *,
    file_path: str,
    frameworks: Iterable[str],
    symbol_lookup: Mapping[Tuple[str, Optional[str], str], ProfileRecord],
) -> Iterator[_EntryPointRecord]:
    for node in tree.body:
        yield from _extract_entry_points_from_node(node, file_path=file_path, frameworks=frameworks, class_name=None, symbol_lookup=symbol_lookup)


def _extract_entry_points_from_node(
    node: ast.AST,
    *,
    file_path: str,
    frameworks: Iterable[str],
    class_name: Optional[str],
    symbol_lookup: Mapping[Tuple[str, Optional[str], str], ProfileRecord],
) -> Iterator[_EntryPointRecord]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for info in _extract_route_decorators(node, frameworks):
            key = (file_path, class_name, node.name)
            profile = symbol_lookup.get(key)
            symbol_label = _derive_symbol_label(profile, class_name, node.name)
            qualified_name = _format_qualified_name(file_path, class_name, node.name)
            doc_summary = _summarise_docstring(ast.get_docstring(node))
            yield _EntryPointRecord(
                call_graph_id=profile.id if profile else None,
                class_name=class_name,
                function_name=node.name,
                symbol=symbol_label,
                qualified_name=qualified_name,
                file_path=file_path,
                line_number=info.lineno,
                route=info.route,
                methods=info.methods,
                framework=info.framework,
                decorator=info.decorator,
                docstring=doc_summary,
            )
    elif isinstance(node, ast.ClassDef):
        for child in node.body:
            yield from _extract_entry_points_from_node(
                child, file_path=file_path, frameworks=frameworks, class_name=node.name, symbol_lookup=symbol_lookup
            )


def _extract_route_decorators(node: ast.AST, frameworks: Iterable[str]) -> Iterator[_DecoratorInfo]:
    framework_set = {fw.lower() for fw in frameworks}
    for decorator in getattr(node, "decorator_list", []):
        info = _parse_route_decorator(decorator, framework_set)
        if info:
            yield info


def _parse_route_decorator(decorator: ast.AST, frameworks: Iterable[str]) -> Optional[_DecoratorInfo]:
    if not isinstance(decorator, ast.Call):
        return None
    base_name, attr_name = _callable_name(decorator.func)
    if attr_name is None:
        return None
    attr_lower = attr_name.lower()
    if attr_lower not in HTTP_METHOD_DECORATORS + ROUTE_DECORATORS:
        return None
    route_path = _extract_route_path(decorator)
    if route_path is None:
        return None
    methods = _extract_http_methods(decorator, attr_lower)
    framework = _infer_framework(base_name, attr_lower, frameworks)
    decorator_repr = f"{base_name}.{attr_name}" if base_name else attr_name
    return _DecoratorInfo(route=route_path, methods=methods, framework=framework, decorator=decorator_repr, lineno=getattr(decorator, "lineno", 0))


def _callable_name(node: ast.AST) -> Tuple[Optional[str], Optional[str]]:
    if isinstance(node, ast.Attribute):
        return _attribute_to_string(node.value), node.attr
    if isinstance(node, ast.Name):
        return None, node.id
    return None, None


def _attribute_to_string(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attribute_to_string(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _extract_route_path(decorator: ast.Call) -> Optional[str]:
    path_node = decorator.args[0] if decorator.args else None
    if path_node is None:
        for kw in decorator.keywords:
            if kw.arg in {"path", "rule", "route"}:
                path_node = kw.value
                break
    if path_node is None:
        return None
    if isinstance(path_node, ast.Constant) and isinstance(path_node.value, str):
        return path_node.value
    try:
        return ast.unparse(path_node)
    except Exception:
        return None


def _extract_http_methods(decorator: ast.Call, attr_name: str) -> Tuple[str, ...]:
    for kw in decorator.keywords:
        if kw.arg in {"methods", "method"}:
            methods = _extract_string_sequence(kw.value)
            if methods:
                return tuple(m.upper() for m in methods if m)
    if attr_name.lower() in HTTP_METHOD_DECORATORS:
        return (attr_name.upper(),)
    if attr_name.lower() == "websocket":
        return ("WEBSOCKET",)
    return ("GET",)


def _extract_string_sequence(node: ast.AST) -> Optional[Sequence[str]]:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = []
        for el in node.elts:
            if isinstance(el, ast.Constant) and isinstance(el.value, str):
                values.append(el.value)
            else:
                return None
        return values
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return None


def _infer_framework(base_name: Optional[str], attr_name: str, frameworks: Iterable[str]) -> str:
    known = {fw.lower() for fw in frameworks}
    attr_lower = attr_name.lower()
    base_lower = (base_name or "").lower()
    if "fastapi" in known and (attr_lower in HTTP_METHOD_DECORATORS or "router" in base_lower):
        return "fastapi"
    if "flask" in known and (attr_lower in HTTP_METHOD_DECORATORS or attr_lower == "route"):
        return "flask"
    if "router" in base_lower:
        return "fastapi"
    if "blueprint" in base_lower or base_lower in {"app", "manager", "bp"}:
        return "flask"
    return "unknown"


def _derive_symbol_label(profile: Optional[ProfileRecord], class_name: Optional[str], function_name: str) -> str:
    if profile and profile.label:
        return profile.label
    return f"{class_name}.{function_name}" if class_name else function_name


def _format_qualified_name(file_path: str, class_name: Optional[str], function_name: str) -> str:
    module_path = file_path.replace("/", ".").removesuffix(".py")
    return f"{module_path}.{class_name}.{function_name}" if class_name else f"{module_path}.{function_name}"


def _summarise_docstring(docstring: Optional[str]) -> Optional[str]:
    if not docstring:
        return None
    stripped = docstring.strip()
    if not stripped:
        return None
    first_line = stripped.splitlines()[0].strip()
    if not first_line:
        return None
    return first_line[:157] + "..." if len(first_line) > 160 else first_line


def _filter_entry_points(
    entries: Sequence[_EntryPointRecord], *, framework: Optional[str], path_contains: Optional[str]
) -> List[_EntryPointRecord]:
    filtered = []
    framework_lower = framework.lower() if framework else None
    path_filter = path_contains.lower() if path_contains else None
    for entry in entries:
        if framework_lower and entry.framework.lower() != framework_lower:
            continue
        if path_filter and path_filter not in entry.route.lower():
            continue
        filtered.append(entry)
    return filtered


def _entry_point_to_payload(entry: _EntryPointRecord, *, include_docstring: bool) -> Dict[str, Any]:
    node_id = entry.call_graph_id or f"python::{entry.file_path}::{entry.function_name}"
    payload: Dict[str, Any] = {
        "symbol": entry.symbol,
        "qualified_name": entry.qualified_name,
        "file_path": entry.file_path,
        "line_number": entry.line_number,
        "route": entry.route,
        "http_methods": list(entry.methods),
        "framework": entry.framework,
        "decorator": entry.decorator,
        "node_id": node_id,
    }
    if entry.call_graph_id:
        payload["call_graph_id"] = entry.call_graph_id
    if include_docstring and entry.docstring:
        payload["docstring"] = entry.docstring
    return payload


def build_list_entry_point_tool(workspace_id: str, database_url: str | None = None) -> BaseTool:
    """Create a list_entry_point tool bound to a specific workspace."""

    @tool(args_schema=ListEntryPointInput)
    def list_entry_point(
        limit: int = 20, framework: Optional[str] = None, path_contains: Optional[str] = None, include_docstring: bool = False
    ) -> List[Dict[str, Any]]:
        """List probable API entry points (e.g., FastAPI routers or Flask views) by inspecting route decorators."""
        entries = _discover_entry_points(workspace_id, database_url)
        filtered = _filter_entry_points(entries, framework=framework, path_contains=path_contains)
        return [_entry_point_to_payload(entry, include_docstring=include_docstring) for entry in filtered[:limit]]

    return list_entry_point


__all__ = ["ListEntryPointInput", "build_list_entry_point_tool"]
