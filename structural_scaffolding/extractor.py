from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .models import Profile


class TreeSitterDependencyError(RuntimeError):
    """Raised when the required Tree-sitter bindings are missing."""


class TreeSitterParser:
    """Light wrapper around a Tree-sitter parser with lazy dependency checks."""

    def __init__(self, language_name: str) -> None:
        self._language_name = language_name
        self._parser = self._build_parser(language_name)

    @staticmethod
    def _build_parser(language_name: str):
        try:
            from tree_sitter import Parser  # type: ignore
        except ImportError as exc:  # pragma: no cover - triggered only when deps missing
            raise TreeSitterDependencyError(
                "Missing dependency 'tree_sitter'. Install with 'pip install tree-sitter tree-sitter-languages'."
            ) from exc

        try:
            from tree_sitter_languages import get_language  # type: ignore
        except ImportError as exc:  # pragma: no cover - triggered only when deps missing
            raise TreeSitterDependencyError(
                "Missing dependency 'tree_sitter_languages'. Install with 'pip install tree-sitter-languages'."
            ) from exc

        language = get_language(language_name)
        parser = Parser()
        parser.set_language(language)
        return parser

    def parse(self, source_bytes: bytes):
        return self._parser.parse(source_bytes)


def node_text(source: bytes, node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8")


def sanitize_call_name(name: str) -> str:
    return re.sub(r"\s+", "", name)


class BaseLanguageHandler:
    language_name: str
    file_extensions: Sequence[str]

    def __init__(self) -> None:
        self._parser = TreeSitterParser(self.language_name)

    def supports(self, path: Path) -> bool:
        return path.suffix in self.file_extensions

    def extract(self, path: Path, relative_path: Path) -> List[Profile]:
        raise NotImplementedError


class PythonHandler(BaseLanguageHandler):
    language_name = "python"
    file_extensions = (".py",)

    def _build_file_id(self, relative_path: Path) -> str:
        return f"{self.language_name}::file::{relative_path.as_posix()}"

    def extract(self, path: Path, relative_path: Path) -> List[Profile]:
        source_bytes = path.read_bytes()
        tree = self._parser.parse(source_bytes)
        root = tree.root_node

        file_id = self._build_file_id(relative_path)
        file_children: List[str] = []
        collected: List[Profile] = []

        for node in root.named_children:
            if node.type == "function_definition":
                function_profile = self._build_function_profile(
                    node=node,
                    source_bytes=source_bytes,
                    relative_path=relative_path,
                    class_stack=(),
                    parent_id=file_id,
                )
                collected.append(function_profile)
                file_children.append(function_profile.id)
            elif node.type == "class_definition":
                class_profile, nested = self._build_class_profile(
                    node=node,
                    source_bytes=source_bytes,
                    relative_path=relative_path,
                    parent_stack=(),
                    parent_id=file_id,
                )
                collected.append(class_profile)
                collected.extend(nested)
                file_children.append(class_profile.id)

        file_profile = Profile(
            id=file_id,
            kind="file",
            file_path=relative_path.as_posix(),
            function_name=None,
            class_name=None,
            start_line=1,
            end_line=root.end_point[0] + 1,
            source_code=source_bytes.decode("utf-8"),
            parent_id=None,
            docstring=self._extract_docstring(root, source_bytes),
            parameters=[],
            calls=[],
            children=file_children,
        )

        return [file_profile, *collected]

    def _build_class_profile(
        self,
        node,
        source_bytes: bytes,
        relative_path: Path,
        parent_stack: Sequence[str],
        parent_id: str,
    ) -> Tuple[Profile, List[Profile]]:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            raise ValueError("Encountered class definition without a name node")

        class_name = node_text(source_bytes, name_node)
        class_stack = (*parent_stack, class_name)
        qualified_class = "::".join(class_stack)
        class_id = f"python::{relative_path.as_posix()}::{qualified_class}"

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        source_code = node_text(source_bytes, node)

        body = node.child_by_field_name("body")
        child_profiles: List[Profile] = []
        child_ids: List[str] = []

        if body is not None:
            for child in body.named_children:
                if child.type == "function_definition":
                    method_profile = self._build_function_profile(
                        node=child,
                        source_bytes=source_bytes,
                        relative_path=relative_path,
                        class_stack=class_stack,
                        parent_id=class_id,
                    )
                    child_profiles.append(method_profile)
                    child_ids.append(method_profile.id)
                elif child.type == "class_definition":
                    nested_class_profile, nested_children = self._build_class_profile(
                        node=child,
                        source_bytes=source_bytes,
                        relative_path=relative_path,
                        parent_stack=class_stack,
                        parent_id=class_id,
                    )
                    child_profiles.append(nested_class_profile)
                    child_profiles.extend(nested_children)
                    child_ids.append(nested_class_profile.id)

        class_profile = Profile(
            id=class_id,
            kind="class",
            file_path=relative_path.as_posix(),
            function_name=None,
            class_name=".".join(class_stack),
            start_line=start_line,
            end_line=end_line,
            source_code=source_code,
            parent_id=parent_id,
            docstring=self._extract_docstring(body, source_bytes),
            parameters=[],
            calls=[],
            children=child_ids,
        )

        return class_profile, child_profiles

    def _build_function_profile(
        self,
        node,
        source_bytes: bytes,
        relative_path: Path,
        class_stack: Sequence[str],
        parent_id: str,
    ) -> Profile:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            raise ValueError("Encountered function definition without a name node")

        function_name = node_text(source_bytes, name_node)
        class_name = ".".join(class_stack) if class_stack else None
        class_segment = "::".join(class_stack)
        id_tail = f"{class_segment}::{function_name}" if class_segment else function_name
        profile_id = f"python::{relative_path.as_posix()}::{id_tail}"

        parameters_node = node.child_by_field_name("parameters")
        parameters = self._extract_parameters(parameters_node, source_bytes) if parameters_node else []

        body_node = node.child_by_field_name("body")
        calls = self._collect_calls(body_node, source_bytes) if body_node else []

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        source_code = node_text(source_bytes, node)

        return Profile(
            id=profile_id,
            kind="method" if class_stack else "function",
            file_path=relative_path.as_posix(),
            function_name=function_name,
            class_name=class_name,
            start_line=start_line,
            end_line=end_line,
            source_code=source_code,
            parent_id=parent_id,
            docstring=self._extract_docstring(body_node, source_bytes),
            parameters=parameters,
            calls=calls,
            children=[],
        )

    def _extract_parameters(self, parameters_node, source_bytes: bytes) -> List[str]:
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

    def _collect_calls(self, body_node, source_bytes: bytes) -> List[str]:
        calls: List[str] = []

        def visit(node):
            if node.type == "call":
                fn_node = node.child_by_field_name("function")
                if fn_node is not None:
                    calls.append(sanitize_call_name(node_text(source_bytes, fn_node)))
            for child in node.named_children:
                visit(child)

        visit(body_node)
        return calls

    def _extract_docstring(self, body_node, source_bytes: bytes) -> Optional[str]:
        if body_node is None:
            return None

        for child in body_node.named_children:
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
                return raw.strip("'\"") or raw

        return None


class ProfileExtractor:
    """Walks a repository and extracts structural profiles."""
    # todo: add more ignored dirs
    DEFAULT_IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "build", "dist"}

    def __init__(
        self,
        root: Path,
        language_handlers: Optional[Iterable[BaseLanguageHandler]] = None,
        ignored_dirs: Optional[Iterable[str]] = None,
    ) -> None:
        self.root = Path(root)
        self.handlers = tuple(language_handlers or (PythonHandler(),))
        self.ignored_dirs = set(ignored_dirs or self.DEFAULT_IGNORED_DIRS)
        self._extension_map = self._build_extension_map(self.handlers)

    @staticmethod
    def _build_extension_map(handlers: Sequence[BaseLanguageHandler]) -> Dict[str, BaseLanguageHandler]:
        extension_map: Dict[str, BaseLanguageHandler] = {}
        for handler in handlers:
            for ext in handler.file_extensions:
                extension_map[ext] = handler
        return extension_map

    def extract(self) -> List[Profile]:
        profiles: List[Profile] = []
        for path, relative in self._iter_source_files():
            handler = self._extension_map.get(path.suffix)
            if handler is None:
                continue
            profiles.extend(handler.extract(path, relative))
        return profiles

    def _iter_source_files(self) -> Iterator[Tuple[Path, Path]]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in self.ignored_dirs]
            for filename in filenames:
                path = Path(dirpath) / filename
                if path.suffix not in self._extension_map:
                    continue
                try:
                    relative = path.relative_to(self.root)
                except ValueError:
                    continue
                yield path, relative


def profiles_to_json(profiles: Sequence[Profile]) -> str:
    data = [profile.to_dict() for profile in profiles]
    return json.dumps(data, ensure_ascii=False, indent=2)


__all__ = ["ProfileExtractor", "profiles_to_json", "TreeSitterDependencyError"]
