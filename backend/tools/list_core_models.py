"""Tool to enumerate Peewee ORM models stored in the structural scaffolding database."""

from __future__ import annotations

import ast
import logging
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import select

from structural_scaffolding.database import ProfileRecord, create_session

DEFAULT_DIRECTORIES: Tuple[str, ...] = ("api", "db")
DEFAULT_LIMIT = 50
LOGGER = logging.getLogger(__name__)


class ListCoreModelsInput(BaseModel):
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=500, description="Maximum number of models to inspect.")
    directories: Optional[List[str]] = Field(
        default=None,
        description="Optional list of path segments that must be contained in the profile's file_path. Defaults to ['api', 'db'].",
    )


@dataclass(frozen=True)
class _FieldSchema:
    name: str
    field_type: str
    qualified_type: str
    args: Tuple[Any, ...]
    kwargs: Mapping[str, Any]
    line: Optional[int]


def _load_model_profiles(
    workspace_id: str, database_url: str | None, limit: int, directories: Optional[Sequence[str]]
) -> List[ProfileRecord]:
    session = create_session(database_url)
    try:
        stmt = select(ProfileRecord).where(ProfileRecord.workspace_id == workspace_id, ProfileRecord.kind == "class")
        results = session.execute(stmt).scalars()
        include_dirs = _normalise_directories(directories)
        matches = []
        for record in results:
            if include_dirs and not _path_matches(record.file_path, include_dirs):
                continue
            matches.append(record)
            if len(matches) >= limit:
                break
        return matches
    finally:
        session.close()


def _normalise_directories(directories: Optional[Sequence[str]]) -> Tuple[str, ...]:
    if not directories:
        return DEFAULT_DIRECTORIES
    cleaned = tuple(seg.strip().strip("/").replace("\\", "/") for seg in directories if seg and seg.strip())
    return cleaned or DEFAULT_DIRECTORIES


def _path_matches(file_path: str, directories: Sequence[str]) -> bool:
    if not directories:
        return True
    normalised = file_path.replace("\\", "/").lstrip("./")
    path_tokens = tuple(part for part in normalised.split("/") if part)
    if not path_tokens:
        return False
    for directory in directories:
        dir_tokens = tuple(part for part in directory.split("/") if part)
        if not dir_tokens:
            continue
        window = len(dir_tokens)
        for start in range(len(path_tokens) - window + 1):
            if path_tokens[start : start + window] == dir_tokens:
                return True
    return False


def _profile_to_schema(record: ProfileRecord) -> Dict[str, Any]:
    source = textwrap.dedent(record.source_code)
    try:
        module = ast.parse(source)
    except SyntaxError as exc:
        LOGGER.debug("Failed to parse class profile %s (%s:%s): %s", record.id, record.file_path, record.start_line, exc)
        return _fallback_schema(record)

    class_node = next((n for n in getattr(module, "body", []) if isinstance(n, ast.ClassDef)), None)
    if class_node is None:
        return _fallback_schema(record)

    fields: List[_FieldSchema] = []
    meta_payload: Dict[str, Any] = {}
    for statement in class_node.body:
        extracted = _extract_field_schema(statement, record.start_line)
        if extracted:
            fields.extend(extracted)
            continue
        if isinstance(statement, ast.ClassDef) and statement.name == "Meta":
            meta_payload = _extract_meta_schema(statement)

    bases = [v for v in (_safe_unparse(base) for base in class_node.bases) if v]
    schema = {
        "node_id": record.id,
        "model_name": class_node.name,
        "qualified_name": _lookup_qualified_name(record),
        "file_path": record.file_path,
        "start_line": record.start_line,
        "end_line": record.end_line,
        "bases": bases or None,
        "fields": [_field_to_payload(f) for f in fields],
        "meta": meta_payload or None,
    }
    return {k: v for k, v in schema.items() if v is not None}


def _extract_field_schema(statement: ast.stmt, class_start: int) -> List[_FieldSchema]:
    collector = []
    if isinstance(statement, ast.Assign):
        for target in statement.targets:
            field = _build_field_schema(target, statement.value, statement.lineno, class_start)
            if field:
                collector.append(field)
    elif isinstance(statement, ast.AnnAssign):
        field = _build_field_schema(statement.target, statement.value, statement.lineno, class_start)
        if field:
            collector.append(field)
    return collector


def _build_field_schema(target: ast.expr, value: Optional[ast.expr], lineno: Optional[int], class_start: int) -> Optional[_FieldSchema]:
    if not isinstance(target, ast.Name) or value is None or not isinstance(value, ast.Call):
        return None
    qualified_type = _safe_unparse(value.func)
    if not qualified_type:
        return None
    field_type = qualified_type.split(".")[-1]
    if not field_type.endswith("Field"):
        return None
    args = tuple(_safe_literal_eval(arg) for arg in value.args)
    kwargs = {kw.arg: _safe_literal_eval(kw.value) for kw in value.keywords if kw.arg}
    absolute_line = class_start + lineno - 1 if lineno else None
    return _FieldSchema(name=target.id, field_type=field_type, qualified_type=qualified_type, args=args, kwargs=kwargs, line=absolute_line)


def _extract_meta_schema(meta_class: ast.ClassDef) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for statement in meta_class.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and statement.value:
                    payload[target.id] = _safe_literal_eval(statement.value)
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value:
            payload[statement.target.id] = _safe_literal_eval(statement.value)
    return payload


def _field_to_payload(field: _FieldSchema) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": field.name, "field_type": field.field_type, "qualified_type": field.qualified_type}
    if field.args:
        payload["args"] = list(field.args)
    if field.kwargs:
        payload["kwargs"] = dict(field.kwargs)
    if field.line is not None:
        payload["line"] = field.line
    return payload


def _lookup_qualified_name(record: ProfileRecord) -> Optional[str]:
    data = getattr(record, "data", None)
    if isinstance(data, dict):
        qualified = data.get("qualified_name") or data.get("dotted_path")
        if isinstance(qualified, str):
            return qualified
    if record.class_name and record.file_path:
        module = Path(record.file_path).with_suffix("").as_posix().replace("/", ".")
        return f"{module}.{record.class_name}"
    return record.class_name


def _safe_literal_eval(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:
        rendered = _safe_unparse(node)
        return rendered if rendered else repr(node)


def _safe_unparse(node: Optional[ast.AST]) -> Optional[str]:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _fallback_schema(record: ProfileRecord) -> Dict[str, Any]:
    return {
        k: v
        for k, v in {
            "node_id": record.id,
            "model_name": record.class_name,
            "qualified_name": _lookup_qualified_name(record),
            "file_path": record.file_path,
            "start_line": record.start_line,
            "end_line": record.end_line,
        }.items()
        if v is not None
    }


def build_list_core_models_tool(workspace_id: str, database_url: str | None = None) -> BaseTool:
    """Create a list_core_models tool bound to a specific workspace."""

    @tool(args_schema=ListCoreModelsInput)
    def list_core_models(limit: int = DEFAULT_LIMIT, directories: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Inspect Peewee model classes captured by structural scaffolding and summarise their schema as JSON."""
        models = _load_model_profiles(workspace_id, database_url, limit, directories)
        return [_profile_to_schema(record) for record in models]

    return list_core_models


__all__ = ["ListCoreModelsInput", "build_list_core_models_tool"]
