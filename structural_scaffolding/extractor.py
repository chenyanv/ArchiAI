from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from structural_scaffolding.handlers.base import BaseLanguageHandler
from structural_scaffolding.handlers.python_handler import PythonHandler
from structural_scaffolding.models import Profile
from structural_scaffolding.parsing import TreeSitterDependencyError


class ProfileExtractor:
    """Walks a repository and extracts structural profiles."""

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
