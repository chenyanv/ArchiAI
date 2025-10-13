from __future__ import annotations

import ast
import logging
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from structural_scaffolding.database import ProfileRecord, create_session

DEFAULT_DIRECTORIES: Tuple[str, ...] = ("api", "db")
DEFAULT_LIMIT = 50
LOGGER = logging.getLogger(__name__)


class ListCoreModelsInput(BaseModel):
    limit: int = Field(
        default=DEFAULT_LIMIT,
        ge=1,
        le=500,
        description="Maximum number of models to inspect (post filtering).",
    )
    directories: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional list of path segments that must be contained in the profile's file_path. "
            "Defaults to ['api', 'db'] if omitted."
        ),
    )
    database_url: Optional[str] = Field(
        default=None,
        description="Optional override for the structural scaffolding database URL.",
    )


@dataclass(frozen=True)
class _FieldSchema:
    name: str
    field_type: str
    qualified_type: str
    args: Tuple[Any, ...]
    kwargs: Mapping[str, Any]
    line: Optional[int]


def build_list_core_models_tool() -> StructuredTool:
    """
    Create a LangGraph-compatible tool that enumerates Peewee ORM models
    stored in the structural scaffolding profile database and returns a JSON schema.
    """

    def _run(
        limit: int = DEFAULT_LIMIT,
        directories: Optional[Sequence[str]] = None,
        database_url: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        session = create_session(database_url)
        try:
            models = _load_model_profiles(
                session=session,
                limit=limit,
                directories=directories,
            )
            return [_profile_to_schema(record) for record in models]
        finally:
            session.close()

    return StructuredTool.from_function(
        func=_run,
        name="list_core_models",
        description=(
            "Inspect Peewee model classes captured by structural scaffolding and "
            "summarise their schema (fields, table metadata) as JSON."
        ),
        args_schema=ListCoreModelsInput,
        return_direct=True,
    )


list_core_models = build_list_core_models_tool()


def _load_model_profiles(
    *,
    session: Session,
    limit: int,
    directories: Optional[Sequence[str]],
) -> List[ProfileRecord]:
    stmt = select(ProfileRecord).where(ProfileRecord.kind == "class")
    results = session.execute(stmt).scalars()
    include_dirs = _normalise_directories(directories)

    matches: List[ProfileRecord] = []
    for record in results:
        if include_dirs and not _path_matches(record.file_path, include_dirs):
            continue
        matches.append(record)
        if len(matches) >= limit:
            break
    return matches


def _normalise_directories(
    directories: Optional[Sequence[str]],
) -> Tuple[str, ...]:
    if not directories:
        return DEFAULT_DIRECTORIES
    cleaned = tuple(
        segment.strip().strip("/").replace("\\", "/")
        for segment in directories
        if segment and segment.strip()
    )
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
        for start in range(0, len(path_tokens) - window + 1):
            if path_tokens[start : start + window] == dir_tokens:
                return True
    return False


def _profile_to_schema(record: ProfileRecord) -> Dict[str, Any]:
    source = textwrap.dedent(record.source_code)
    try:
        module = ast.parse(source)
    except SyntaxError as exc:
        LOGGER.debug(
            "Failed to parse class profile %s (%s:%s): %s",
            record.id,
            record.file_path,
            record.start_line,
            exc,
        )
        return _fallback_schema(record)

    class_node = _first_class_def(module)
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

    bases = [
        value
        for value in (_safe_unparse(base) for base in class_node.bases)
        if value
    ]

    schema = {
        "model_name": class_node.name,
        "qualified_name": _lookup_qualified_name(record),
        "file_path": record.file_path,
        "start_line": record.start_line,
        "end_line": record.end_line,
        "bases": bases or None,
        "fields": [_field_to_payload(field) for field in fields],
        "meta": meta_payload or None,
    }
    schema = {key: value for key, value in schema.items() if value is not None}
    return schema


def _first_class_def(module: ast.AST) -> Optional[ast.ClassDef]:
    for node in getattr(module, "body", []):
        if isinstance(node, ast.ClassDef):
            return node
    return None


def _extract_field_schema(
    statement: ast.stmt,
    class_start: int,
) -> List[_FieldSchema]:
    collector: List[_FieldSchema] = []
    if isinstance(statement, ast.Assign):
        for target in statement.targets:
            field = _build_field_schema(target, statement.value, statement.lineno, class_start)
            if field:
                collector.append(field)
    elif isinstance(statement, ast.AnnAssign):
        field = _build_field_schema(
            statement.target,
            statement.value,
            statement.lineno,
            class_start,
        )
        if field:
            collector.append(field)
    return collector


def _build_field_schema(
    target: ast.expr,
    value: Optional[ast.expr],
    lineno: Optional[int],
    class_start: int,
) -> Optional[_FieldSchema]:
    if not isinstance(target, ast.Name) or value is None:
        return None
    if not isinstance(value, ast.Call):
        return None

    qualified_type = _safe_unparse(value.func)
    if not qualified_type:
        return None

    field_type = qualified_type.split(".")[-1]
    if not field_type.endswith("Field"):
        return None

    args = tuple(_safe_literal_eval(arg) for arg in value.args)
    kwargs = {
        kw.arg: _safe_literal_eval(kw.value)
        for kw in value.keywords
        if kw.arg
    }
    absolute_line = None
    if lineno is not None:
        absolute_line = class_start + lineno - 1

    return _FieldSchema(
        name=target.id,
        field_type=field_type,
        qualified_type=qualified_type,
        args=args,
        kwargs=kwargs,
        line=absolute_line,
    )


def _extract_meta_schema(meta_class: ast.ClassDef) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for statement in meta_class.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                _assign_meta_value(payload, target, statement.value)
        elif isinstance(statement, ast.AnnAssign):
            _assign_meta_value(payload, statement.target, statement.value)
    return payload


def _assign_meta_value(
    payload: Dict[str, Any],
    target: ast.expr,
    value: Optional[ast.expr],
) -> None:
    if not isinstance(target, ast.Name) or value is None:
        return
    payload[target.id] = _safe_literal_eval(value)


def _field_to_payload(field: _FieldSchema) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": field.name,
        "field_type": field.field_type,
        "qualified_type": field.qualified_type,
    }
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
        return rendered if rendered is not None else repr(node)


def _safe_unparse(node: Optional[ast.AST]) -> Optional[str]:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _fallback_schema(record: ProfileRecord) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model_name": record.class_name,
        "qualified_name": _lookup_qualified_name(record),
        "file_path": record.file_path,
        "start_line": record.start_line,
        "end_line": record.end_line,
    }
    return {key: value for key, value in payload.items() if value is not None}


__all__ = [
    "build_list_core_models_tool",
    "list_core_models",
]
