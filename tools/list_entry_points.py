from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

DEFAULT_GRAPH_PATH = Path("results/graphs/call_graph.json")
REPO_ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOTS: Tuple[Path, ...] = (REPO_ROOT, REPO_ROOT / "ragflow-main")

HTTP_METHOD_DECORATORS: Tuple[str, ...] = (
    "get",
    "post",
    "put",
    "delete",
    "patch",
    "options",
    "head",
    "trace",
)
ROUTE_DECORATORS: Tuple[str, ...] = ("route", "api_route", "websocket")


class ListEntryPointInput(BaseModel):
    limit: int = Field(
        20,
        ge=1,
        le=200,
        description="Maximum number of entry points to return.",
    )
    framework: Optional[str] = Field(
        None,
        description="Optional framework filter (e.g. fastapi, flask).",
    )
    path_contains: Optional[str] = Field(
        None,
        description="Restrict results to routes containing this substring.",
    )
    include_docstring: bool = Field(
        False,
        description="Whether to include a short docstring summary when available.",
    )


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


def build_list_entry_point_tool(
    graph_path: Path | str = DEFAULT_GRAPH_PATH,
) -> StructuredTool:
    """
    Create a LangGraph-compatible tool that enumerates likely HTTP entry points
    (FastAPI/Flask routes) discovered in the project.
    """
    resolved_path = Path(graph_path).expanduser().resolve()

    def _run(
        limit: int = 20,
        framework: Optional[str] = None,
        path_contains: Optional[str] = None,
        include_docstring: bool = False,
    ) -> List[Dict[str, Any]]:
        entries = _discover_entry_points(str(resolved_path))
        filtered = _filter_entry_points(
            entries,
            framework=framework,
            path_contains=path_contains,
        )
        sliced = filtered[:limit]
        return [
            _entry_point_to_payload(entry, include_docstring=include_docstring)
            for entry in sliced
        ]

    return StructuredTool.from_function(
        func=_run,
        name="list_entry_point",
        description=(
            "List probable API entry points (e.g., FastAPI routers or Flask views) "
            "by inspecting route decorators across the codebase. "
            "Useful for identifying HTTP endpoints and their route metadata."
        ),
        args_schema=ListEntryPointInput,
        return_direct=True,
    )


list_entry_point_tool = build_list_entry_point_tool()


@lru_cache(maxsize=1)
def _discover_entry_points(graph_path: str) -> Tuple[_EntryPointRecord, ...]:
    nodes = _load_call_graph_nodes(Path(graph_path))
    file_nodes = (
        node
        for node in nodes
        if node.get("kind") == "file" and str(node.get("file_path", "")).endswith(".py")
    )
    function_lookup = _build_symbol_lookup(nodes)

    records: List[_EntryPointRecord] = []
    for node in file_nodes:
        file_path = node.get("file_path")
        if not file_path:
            continue

        source_path = _resolve_source_path(file_path)
        if source_path is None:
            continue

        try:
            source_text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if "@" not in source_text:
            continue

        try:
            syntax_tree = ast.parse(source_text, filename=str(source_path))
        except SyntaxError:
            continue

        frameworks = _detect_frameworks(syntax_tree)
        for entry in _iter_entry_points(
            syntax_tree,
            file_path=file_path,
            frameworks=frameworks,
            symbol_lookup=function_lookup,
        ):
            records.append(entry)

    records.sort(key=lambda entry: (entry.route, entry.file_path, entry.line_number))
    return tuple(records)


def _load_call_graph_nodes(path: Path) -> Tuple[Mapping[str, Any], ...]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (FileNotFoundError, json.JSONDecodeError):
        return tuple()

    nodes = payload.get("nodes", [])
    return tuple(node for node in nodes if isinstance(node, dict))


def _build_symbol_lookup(
    nodes: Sequence[Mapping[str, Any]],
) -> Dict[Tuple[str, Optional[str], str], Mapping[str, Any]]:
    lookup: Dict[Tuple[str, Optional[str], str], Mapping[str, Any]] = {}
    for node in nodes:
        file_path = node.get("file_path")
        function_name = node.get("function_name")
        if not file_path or not function_name:
            continue

        class_name = node.get("class_name")
        if class_name:
            key = (str(file_path), str(class_name), str(function_name))
        else:
            key = (str(file_path), None, str(function_name))
        lookup[key] = node
    return lookup


def _resolve_source_path(file_path: str) -> Optional[Path]:
    candidate = Path(file_path)
    if candidate.is_absolute():
        if candidate.exists():
            return candidate
        return None

    for root in SEARCH_ROOTS:
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    return None


def _detect_frameworks(tree: ast.AST) -> Iterable[str]:
    frameworks: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name.startswith("fastapi"):
                    frameworks.add("fastapi")
                if name.startswith("flask"):
                    frameworks.add("flask")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("fastapi"):
                frameworks.add("fastapi")
            if module.startswith("flask"):
                frameworks.add("flask")
    return frameworks


def _iter_entry_points(
    tree: ast.AST,
    *,
    file_path: str,
    frameworks: Iterable[str],
    symbol_lookup: Mapping[Tuple[str, Optional[str], str], Mapping[str, Any]],
) -> Iterator[_EntryPointRecord]:
    framework_set = set(frameworks)

    for node in tree.body:
        yield from _extract_entry_points_from_node(
            node,
            file_path=file_path,
            frameworks=framework_set,
            class_name=None,
            symbol_lookup=symbol_lookup,
        )


def _extract_entry_points_from_node(
    node: ast.AST,
    *,
    file_path: str,
    frameworks: Iterable[str],
    class_name: Optional[str],
    symbol_lookup: Mapping[Tuple[str, Optional[str], str], Mapping[str, Any]],
) -> Iterator[_EntryPointRecord]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for info in _extract_route_decorators(node, frameworks):
            key = (file_path, class_name, node.name)
            cg_node = symbol_lookup.get(key)
            symbol_label = _derive_symbol_label(cg_node, class_name, node.name)
            qualified_name = _format_qualified_name(file_path, class_name, node.name)
            doc_summary = _summarise_docstring(ast.get_docstring(node))
            yield _EntryPointRecord(
                call_graph_id=str(cg_node.get("id")) if cg_node else None,
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
                child,
                file_path=file_path,
                frameworks=frameworks,
                class_name=node.name,
                symbol_lookup=symbol_lookup,
            )


def _extract_route_decorators(
    node: ast.AST,
    frameworks: Iterable[str],
) -> Iterator[_DecoratorInfo]:
    framework_set = {fw.lower() for fw in frameworks}
    decorators = getattr(node, "decorator_list", [])
    for decorator in decorators:
        info = _parse_route_decorator(decorator, framework_set)
        if info is None:
            continue
        yield info


def _parse_route_decorator(
    decorator: ast.AST,
    frameworks: Iterable[str],
) -> Optional[_DecoratorInfo]:
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
    decorator_repr = _decorator_repr(base_name, attr_name)
    lineno = getattr(decorator, "lineno", getattr(decorator, "lineno", 0))

    return _DecoratorInfo(
        route=route_path,
        methods=methods,
        framework=framework,
        decorator=decorator_repr,
        lineno=lineno,
    )


def _callable_name(node: ast.AST) -> Tuple[Optional[str], Optional[str]]:
    if isinstance(node, ast.Attribute):
        base = _attribute_to_string(node.value)
        return base, node.attr
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
        for keyword in decorator.keywords:
            if keyword.arg in {"path", "rule", "route"}:
                path_node = keyword.value
                break
    if path_node is None:
        return None

    constant = _literal_string(path_node)
    if constant is not None:
        return constant

    try:
        # Fall back to source representation for non-literal paths.
        return ast.unparse(path_node)  # type: ignore[attr-defined]
    except Exception:
        return None


def _literal_string(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_http_methods(decorator: ast.Call, attr_name: str) -> Tuple[str, ...]:
    explicit_methods = None
    for keyword in decorator.keywords:
        if keyword.arg == "methods":
            explicit_methods = _extract_string_sequence(keyword.value)
            break
        if keyword.arg == "method":
            explicit_methods = _extract_string_sequence(keyword.value)
            break

    if explicit_methods:
        return tuple(method.upper() for method in explicit_methods if method)

    if attr_name.lower() in HTTP_METHOD_DECORATORS:
        return (attr_name.upper(),)
    if attr_name.lower() == "websocket":
        return ("WEBSOCKET",)
    return ("GET",)


def _extract_string_sequence(node: ast.AST) -> Optional[Sequence[str]]:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values: List[str] = []
        for element in node.elts:
            value = _literal_string(element)
            if value is None:
                return None
            values.append(value)
        return values
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return None


def _infer_framework(
    base_name: Optional[str],
    attr_name: str,
    frameworks: Iterable[str],
) -> str:
    known = {fw.lower() for fw in frameworks}
    attr_lower = attr_name.lower()
    base_lower = (base_name or "").lower()

    if "fastapi" in known:
        if attr_lower in HTTP_METHOD_DECORATORS or "router" in base_lower:
            return "fastapi"
    if "flask" in known:
        if attr_lower in HTTP_METHOD_DECORATORS or attr_lower == "route":
            return "flask"

    if "router" in base_lower or base_lower.endswith("router"):
        return "fastapi"
    if "blueprint" in base_lower or base_lower in {"app", "manager", "bp"}:
        return "flask"

    return "unknown"


def _decorator_repr(base_name: Optional[str], attr_name: str) -> str:
    if base_name:
        return f"{base_name}.{attr_name}"
    return attr_name


def _derive_symbol_label(
    node: Optional[Mapping[str, Any]],
    class_name: Optional[str],
    function_name: str,
) -> str:
    if node and "label" in node:
        return str(node["label"])
    if class_name:
        return f"{class_name}.{function_name}"
    return function_name


def _format_qualified_name(
    file_path: str,
    class_name: Optional[str],
    function_name: str,
) -> str:
    module_path = file_path.replace("/", ".").removesuffix(".py")
    if class_name:
        return f"{module_path}.{class_name}.{function_name}"
    return f"{module_path}.{function_name}"


def _summarise_docstring(docstring: Optional[str]) -> Optional[str]:
    if not docstring:
        return None
    stripped = docstring.strip()
    if not stripped:
        return None
    first_line = stripped.splitlines()[0].strip()
    if not first_line:
        return None
    if len(first_line) <= 160:
        return first_line
    return first_line[:157] + "..."


def _filter_entry_points(
    entries: Sequence[_EntryPointRecord],
    *,
    framework: Optional[str],
    path_contains: Optional[str],
) -> List[_EntryPointRecord]:
    filtered: List[_EntryPointRecord] = []
    framework_lower = framework.lower() if framework else None
    path_filter = path_contains.lower() if path_contains else None

    for entry in entries:
        if framework_lower and entry.framework.lower() != framework_lower:
            continue
        if path_filter and path_filter not in entry.route.lower():
            continue
        filtered.append(entry)
    return filtered


def _resolve_entry_point_node_id(entry: _EntryPointRecord) -> str:
    """
    Prefer the structural graph identifier when available; otherwise synthesise
    a stable node id so downstream consumers can still correlate the handler.
    """
    if entry.call_graph_id:
        return str(entry.call_graph_id)

    file_path = entry.file_path.replace("\\", "/").lstrip("./")
    base = f"python::{file_path}"
    if entry.class_name:
        return f"{base}::{entry.class_name}::{entry.function_name}"
    return f"{base}::{entry.function_name}"


def _entry_point_to_payload(
    entry: _EntryPointRecord,
    *,
    include_docstring: bool,
) -> Dict[str, Any]:
    node_id = _resolve_entry_point_node_id(entry)
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
