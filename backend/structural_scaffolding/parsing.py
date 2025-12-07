from __future__ import annotations

import re
from typing import Any


class TreeSitterDependencyError(RuntimeError):
    """Raised when the required Tree-sitter bindings are missing."""


class TreeSitterParser:
    """Light wrapper around a Tree-sitter parser with lazy dependency checks."""

    def __init__(self, language_name: str) -> None:
        self._parser = self._build_parser(language_name)

    @staticmethod
    def _build_parser(language_name: str):
        try:
            from tree_sitter_languages import get_parser  # type: ignore
        except ImportError:
            get_parser = None

        if get_parser is not None:
            try:
                return get_parser(language_name)
            except Exception as exc:  # pragma: no cover - fallback handles compatibility gaps
                last_error = exc
            else:
                last_error = None
        else:
            last_error = None

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

        try:
            language = get_language(language_name)
        except Exception as exc:
            if last_error is not None:
                raise TreeSitterDependencyError(str(last_error)) from exc
            raise

        parser = Parser()
        parser.set_language(language)
        return parser

    def parse(self, source_bytes: bytes) -> Any:
        return self._parser.parse(source_bytes)


def node_text(source: bytes, node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8")


def sanitize_call_name(name: str) -> str:
    return re.sub(r"\s+", "", name)


__all__ = [
    "TreeSitterDependencyError",
    "TreeSitterParser",
    "node_text",
    "sanitize_call_name",
]
