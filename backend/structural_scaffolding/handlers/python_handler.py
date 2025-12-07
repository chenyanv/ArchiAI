from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from structural_scaffolding.models import (
    CallSite,
    ImportSite,
    InheritanceRef,
    Profile,
    UseSite,
)
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
        profiles = [file_profile, *nested_profiles]
        self._populate_semantic_metadata(profiles)
        return profiles

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

    def _populate_semantic_metadata(self, profiles: List[Profile]) -> None:
        analyzer = PythonSemanticAnalyzer(self._context)
        analysis = analyzer.analyze()
        if analysis is None:
            return

        profile_lookup: Dict[str, Profile] = {profile.id: profile for profile in profiles}

        file_id = self._context.build_file_id()
        file_profile = profile_lookup.get(file_id)
        if file_profile is not None:
            file_profile.import_sites = analysis.imports

        for profile_id, call_sites in analysis.call_sites.items():
            profile = profile_lookup.get(profile_id)
            if profile is None:
                continue
            profile.call_sites = call_sites
            profile.calls = [site.expression for site in call_sites]

        for profile_id, uses in analysis.uses.items():
            profile = profile_lookup.get(profile_id)
            if profile is None:
                continue
            if profile.uses:
                profile.uses.extend(uses)
            else:
                profile.uses = list(uses)

        for profile_id, inheritance in analysis.inheritance.items():
            profile = profile_lookup.get(profile_id)
            if profile is None:
                continue
            profile.inheritance = inheritance

    def _build_class_profile(
        self,
        node,
        parent_stack: Sequence[str],
        parent_id: str,
        *,
        decorated_node=None,
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
            node=decorated_node or node,
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
        *,
        decorated_node=None,
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
            node=decorated_node or node,
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
            target = child
            decorated_wrapper = None
            if child.type == "decorated_definition":
                definition = child.child_by_field_name("definition")
                if definition is None:
                    continue
                target = definition
                decorated_wrapper = child

            if target.type in {"function_definition", "async_function_definition"}:
                profile = self._build_function_profile(
                    node=target,
                    class_stack=class_stack,
                    parent_id=parent_id,
                    decorated_node=decorated_wrapper,
                )
                collected.append(profile)
                child_ids.append(profile.id)
            elif target.type == "class_definition":
                class_profile, nested = self._build_class_profile(
                    node=target,
                    parent_stack=class_stack,
                    parent_id=parent_id,
                    decorated_node=decorated_wrapper,
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


@dataclass(slots=True)
class PythonSemanticAnalysis:
    imports: List[ImportSite]
    call_sites: Dict[str, List[CallSite]]
    uses: Dict[str, List[UseSite]]
    inheritance: Dict[str, List[InheritanceRef]]


class PythonSemanticAnalyzer(ast.NodeVisitor):
    def __init__(self, context: PythonNodeContext) -> None:
        self._context = context
        self._path_str = context.relative_path.as_posix()
        self._module_path = self._derive_module_path()
        self._file_id = context.build_file_id()
        self._imports: List[ImportSite] = []
        self._call_sites: Dict[str, List[CallSite]] = defaultdict(list)
        self._uses: Dict[str, List[UseSite]] = defaultdict(list)
        self._inheritance: Dict[str, List[InheritanceRef]] = defaultdict(list)
        self._class_stack: List[str] = []
        self._function_stack: List[str] = []

    def analyze(self) -> PythonSemanticAnalysis | None:
        try:
            tree = ast.parse(self._context.source_text)
        except SyntaxError:
            return None
        self.visit(tree)
        return PythonSemanticAnalysis(
            imports=list(self._imports),
            call_sites={key: list(value) for key, value in self._call_sites.items() if value},
            uses={key: list(value) for key, value in self._uses.items() if value},
            inheritance={key: list(value) for key, value in self._inheritance.items() if value},
        )

    def visit_Import(self, node: ast.Import) -> None:
        line = getattr(node, "lineno", 0)
        for alias in node.names:
            module = sanitize_call_name(alias.name)
            site = ImportSite(
                module=module or None,
                name=None,
                alias=alias.asname,
                line=line,
                level=0,
                is_star=False,
            )
            self._add_import_site(site)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        line = getattr(node, "lineno", 0)
        level = int(getattr(node, "level", 0) or 0)
        module = self._resolve_relative_import(node.module, level)
        for alias in node.names:
            is_star = alias.name == "*"
            name = None if is_star else sanitize_call_name(alias.name)
            site = ImportSite(
                module=module,
                name=name,
                alias=alias.asname,
                line=line,
                level=level,
                is_star=is_star,
            )
            self._add_import_site(site)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        class_id = self._build_class_id()
        fallback_line = getattr(node, "lineno", 0)

        for base in node.bases:
            symbol = self._expr_to_name(base)
            if not symbol:
                continue
            ref = InheritanceRef(symbol=symbol, line=getattr(base, "lineno", fallback_line))
            self._append_unique(self._inheritance[class_id], ref)

        self._record_decorators(class_id, node.decorator_list, fallback_line)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Calls are processed explicitly via FunctionCallVisitor to avoid duplicates.
        self.generic_visit(node)

    def _handle_function(self, node: ast.AST) -> None:
        name = getattr(node, "name", None)
        if not name:
            return

        if self._function_stack:
            self._function_stack.append(name)
            self.generic_visit(node)
            self._function_stack.pop()
            return

        profile_id = self._build_function_id(name)
        fallback_line = getattr(node, "lineno", 0)

        self._function_stack.append(name)
        decorator_list = getattr(node, "decorator_list", [])
        self._record_decorators(profile_id, decorator_list, fallback_line)
        self._record_type_hints(profile_id, node)

        call_visitor = _FunctionCallVisitor(self._expr_to_name)
        call_visitor.visit(node)
        for expression, line in call_visitor.calls:
            site = CallSite(expression=expression, line=line)
            self._append_unique(self._call_sites[profile_id], site)

        self.generic_visit(node)
        self._function_stack.pop()

    def _derive_module_path(self) -> str:
        path = self._path_str
        if path.endswith(".py"):
            path = path[:-3]
        return path.replace("/", ".")

    def _resolve_relative_import(self, module: Optional[str], level: int) -> Optional[str]:
        if level <= 0:
            return sanitize_call_name(module) if module else module

        module_tokens = [token for token in self._module_path.split(".") if token]
        if level > len(module_tokens):
            prefix: List[str] = []
        else:
            prefix = module_tokens[:-level]

        module_suffix: List[str] = []
        if module:
            module_suffix = [token for token in sanitize_call_name(module).split(".") if token]

        combined = [*prefix, *module_suffix]
        if not combined:
            return None
        return ".".join(combined)

    def _build_class_id(self) -> str:
        qualified = "::".join(self._class_stack)
        return f"python::{self._path_str}::{qualified}"

    def _build_function_id(self, function_name: str) -> str:
        class_segment = "::".join(self._class_stack)
        if class_segment:
            qualified = f"{class_segment}::{function_name}"
        else:
            qualified = function_name
        return f"python::{self._path_str}::{qualified}"

    def _record_decorators(self, profile_id: str, decorators: Iterable[ast.AST], fallback_line: int) -> None:
        for decorator in decorators or ():
            symbol = self._expr_to_name(decorator)
            if not symbol:
                continue
            use = UseSite(
                symbol=symbol,
                use_kind="DECORATOR",
                line=getattr(decorator, "lineno", fallback_line),
                detail=None,
            )
            self._append_unique(self._uses[profile_id], use)

    def _record_type_hints(self, profile_id: str, node: ast.AST) -> None:
        parameters: List[ast.arg] = []
        args = getattr(node, "args", None)
        if args is not None:
            parameters.extend(getattr(args, "posonlyargs", []))
            parameters.extend(getattr(args, "args", []))
            vararg = getattr(args, "vararg", None)
            if vararg is not None:
                parameters.append(vararg)
            parameters.extend(getattr(args, "kwonlyargs", []))
            kwarg = getattr(args, "kwarg", None)
            if kwarg is not None:
                parameters.append(kwarg)

        for parameter in parameters:
            annotation = getattr(parameter, "annotation", None)
            if annotation is None:
                continue
            detail = f"parameter:{getattr(parameter, 'arg', '')}"
            self._record_annotation(profile_id, annotation, detail)

        returns = getattr(node, "returns", None)
        if returns is not None:
            self._record_annotation(profile_id, returns, "return")

    def _record_annotation(self, profile_id: str, annotation: ast.AST, detail: str) -> None:
        for symbol in self._collect_annotation_symbols(annotation):
            if not symbol:
                continue
            use = UseSite(
                symbol=symbol,
                use_kind="TYPE_HINT",
                line=getattr(annotation, "lineno", 0),
                detail=detail,
            )
            self._append_unique(self._uses[profile_id], use)

    def _collect_annotation_symbols(self, annotation: ast.AST) -> Set[str]:
        symbols: Set[str] = set()
        for node in ast.walk(annotation):
            if isinstance(node, ast.Name):
                identifier = node.id
                if identifier in {"self", "cls"}:
                    continue
                symbols.add(sanitize_call_name(identifier))
            elif isinstance(node, ast.Attribute):
                name = self._expr_to_name(node)
                if name:
                    symbols.add(name)
        return {symbol for symbol in symbols if symbol}

    def _expr_to_name(self, expr: ast.AST | None) -> Optional[str]:
        if expr is None:
            return None
        if isinstance(expr, ast.Name):
            return sanitize_call_name(expr.id)
        if isinstance(expr, ast.Attribute):
            parts: List[str] = []
            current = expr
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            else:
                return None
            return sanitize_call_name(".".join(reversed(parts)))
        if isinstance(expr, ast.Subscript):
            return self._expr_to_name(expr.value)
        if isinstance(expr, ast.Call):
            return self._expr_to_name(expr.func)
        if hasattr(ast, "unparse"):
            try:
                return sanitize_call_name(ast.unparse(expr))
            except Exception:
                return None
        return None

    def _add_import_site(self, site: ImportSite) -> None:
        if site.is_star:
            # Star imports provide little value for intra-repo connections.
            return
        if any(existing == site for existing in self._imports):
            return
        self._imports.append(site)

    @staticmethod
    def _append_unique(collection: List, item) -> None:
        if item not in collection:
            collection.append(item)


class _FunctionCallVisitor(ast.NodeVisitor):
    def __init__(self, expr_to_name) -> None:
        self._expr_to_name = expr_to_name
        self.calls: List[Tuple[str, int]] = []
        self._function_depth = 0

    def visit_Call(self, node: ast.Call) -> None:
        name = self._expr_to_name(getattr(node, "func", None))
        if name:
            self.calls.append((name, getattr(node, "lineno", 0)))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if self._function_depth > 0:
            return
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if self._function_depth > 0:
            return
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

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
