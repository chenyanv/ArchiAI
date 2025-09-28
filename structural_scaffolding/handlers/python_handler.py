from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from structural_scaffolding.models import Profile
from structural_scaffolding.parsing import TreeSitterParser, node_text, sanitize_call_name

from .base import BaseLanguageHandler


@dataclass(slots=True)
class PythonNodeContext:
    source_bytes: bytes
    relative_path: Path

    @property
    def source_text(self) -> str:
        return self.source_bytes.decode("utf-8")

    def build_file_id(self) -> str:
        return f"python::file::{self.relative_path.as_posix()}"


class PythonProfileBuilder:
    def __init__(self, parser: TreeSitterParser, context: PythonNodeContext) -> None:
        self._parser = parser
        self._context = context
        self._path_str = context.relative_path.as_posix()

    def build_profiles(self) -> List[Profile]:
        source_tree = self._parser.parse(self._context.source_bytes)
        root = source_tree.root_node

        file_profile, nested_profiles = self._build_file_profile(root)
        return [file_profile, *nested_profiles]

    def _build_file_profile(self, root_node) -> Tuple[Profile, List[Profile]]:
        file_id = self._context.build_file_id()
        child_profiles, child_ids = self._collect_child_profiles(
            parent_node=root_node,
            class_stack=(),
            parent_id=file_id,
        )

        file_profile = self._create_profile(
            profile_id=file_id,
            kind="file",
            node=None,
            source_code=self._context.source_text,
            parent_id=None,
            class_name=None,
            function_name=None,
            doc_node=root_node,
            parameters=[],
            calls=[],
            children=child_ids,
            start_line=1,
            end_line=root_node.end_point[0] + 1,
        )

        return file_profile, child_profiles

    def _build_class_profile(
        self,
        node,
        parent_stack: Sequence[str],
        parent_id: str,
    ) -> Tuple[Profile, List[Profile]]:
        class_name = get_identifier(node, self._context.source_bytes, "name")
        class_stack = (*parent_stack, class_name)
        qualified_class = "::".join(class_stack)
        class_id = f"python::{self._path_str}::{qualified_class}"

        body = node.child_by_field_name("body")
        child_profiles, child_ids = self._collect_child_profiles(
            parent_node=body,
            class_stack=class_stack,
            parent_id=class_id,
        )

        class_profile = self._create_profile(
            profile_id=class_id,
            kind="class",
            node=node,
            parent_id=parent_id,
            class_name=".".join(class_stack),
            function_name=None,
            doc_node=body,
            parameters=[],
            calls=[],
            children=child_ids,
        )

        return class_profile, child_profiles

    def _build_function_profile(
        self,
        node,
        class_stack: Sequence[str],
        parent_id: str,
    ) -> Profile:
        function_name = get_identifier(node, self._context.source_bytes, "name")
        class_name = ".".join(class_stack) if class_stack else None
        class_segment = "::".join(class_stack)
        id_tail = f"{class_segment}::{function_name}" if class_segment else function_name
        profile_id = f"python::{self._path_str}::{id_tail}"

        parameters_node = node.child_by_field_name("parameters")
        parameters = extract_parameters(parameters_node, self._context.source_bytes)

        body_node = node.child_by_field_name("body")
        calls = collect_calls(body_node, self._context.source_bytes)

        return self._create_profile(
            profile_id=profile_id,
            kind="method" if class_stack else "function",
            node=node,
            parent_id=parent_id,
            class_name=class_name,
            function_name=function_name,
            doc_node=body_node,
            parameters=parameters,
            calls=calls,
            children=[],
        )

    def _collect_child_profiles(
        self,
        parent_node,
        class_stack: Sequence[str],
        parent_id: str,
    ) -> Tuple[List[Profile], List[str]]:
        if parent_node is None:
            return [], []

        collected: List[Profile] = []
        child_ids: List[str] = []

        for child in parent_node.named_children:
            if child.type == "function_definition":
                profile = self._build_function_profile(
                    node=child,
                    class_stack=class_stack,
                    parent_id=parent_id,
                )
                collected.append(profile)
                child_ids.append(profile.id)
            elif child.type == "class_definition":
                class_profile, nested = self._build_class_profile(
                    node=child,
                    parent_stack=class_stack,
                    parent_id=parent_id,
                )
                collected.append(class_profile)
                child_ids.append(class_profile.id)
                collected.extend(nested)
            # Ignore other node types

        return collected, child_ids

    def _create_profile(
        self,
        *,
        profile_id: str,
        kind: str,
        node,
        parent_id: Optional[str],
        class_name: Optional[str],
        function_name: Optional[str],
        doc_node,
        parameters: List[str],
        calls: List[str],
        children: List[str],
        source_code: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> Profile:
        if node is not None:
            source_code = source_code or node_text(self._context.source_bytes, node)
            start_line = start_line or (node.start_point[0] + 1)
            end_line = end_line or (node.end_point[0] + 1)
        else:
            # For file nodes we expect overrides to be supplied explicitly.
            if source_code is None or start_line is None or end_line is None:
                raise ValueError("File profile requires explicit source and line bounds")

        return Profile(
            id=profile_id,
            kind=kind,
            file_path=self._path_str,
            function_name=function_name,
            class_name=class_name,
            start_line=start_line,
            end_line=end_line,
            source_code=source_code,
            parent_id=parent_id,
            docstring=extract_docstring(doc_node, self._context.source_bytes),
            parameters=parameters,
            calls=calls,
            children=children,
        )


class PythonHandler(BaseLanguageHandler):
    language_name = "python"
    file_extensions = (".py",)

    def extract(self, path: Path, relative_path: Path) -> List[Profile]:
        source_bytes = path.read_bytes()
        context = PythonNodeContext(source_bytes=source_bytes, relative_path=relative_path)
        builder = PythonProfileBuilder(self._parser, context)
        return builder.build_profiles()


def get_identifier(node, source_bytes: bytes, field_name: str) -> str:
    name_node = node.child_by_field_name(field_name)
    if name_node is None:
        raise ValueError(f"Expected field '{field_name}' to be present on node '{node.type}'")
    return node_text(source_bytes, name_node)


def extract_parameters(parameters_node, source_bytes: bytes) -> List[str]:
    if parameters_node is None:
        return []

    parameters: List[str] = []
    for child in parameters_node.named_children:
        if child.type == "identifier":
            parameters.append(node_text(source_bytes, child))
        elif child.type in {"default_parameter", "typed_parameter", "typed_default_parameter"}:
            name_child = child.child_by_field_name("name")
            if name_child is not None:
                parameters.append(node_text(source_bytes, name_child))
        elif child.type in {"list_splat", "dictionary_splat"}:
            name_child = child.child_by_field_name("name")
            if name_child is not None:
                prefix = "*" if child.type == "list_splat" else "**"
                parameters.append(prefix + node_text(source_bytes, name_child))
    return parameters


def collect_calls(body_node, source_bytes: bytes) -> List[str]:
    if body_node is None:
        return []

    calls: List[str] = []

    def visit(node) -> None:
        if node.type == "call":
            fn_node = node.child_by_field_name("function")
            if fn_node is not None:
                calls.append(sanitize_call_name(node_text(source_bytes, fn_node)))
        for child in node.named_children:
            visit(child)

    visit(body_node)
    return calls


def extract_docstring(node, source_bytes: bytes) -> Optional[str]:
    if node is None:
        return None

    for child in node.named_children:
        if child.type != "expression_statement":
            break

        expr_node = child.child_by_field_name("expression")
        if expr_node is None:
            break

        if expr_node.type not in {"string", "concatenated_string"}:
            break

        raw = node_text(source_bytes, expr_node)
        try:
            return ast.literal_eval(raw)
        except Exception:
            stripped = raw.strip('\"\'')
            return stripped or raw

    return None


__all__ = [
    "PythonHandler",
    "PythonProfileBuilder",
    "collect_calls",
    "extract_docstring",
    "extract_parameters",
]
