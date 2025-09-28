from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

from structural_scaffolding.models import Profile
from structural_scaffolding.parsing import TreeSitterParser


class BaseLanguageHandler:
    language_name: str
    file_extensions: Sequence[str]

    def __init__(self) -> None:
        self._parser = TreeSitterParser(self.language_name)

    def supports(self, path: Path) -> bool:
        return path.suffix in self.file_extensions

    def extract(self, path: Path, relative_path: Path) -> List[Profile]:
        raise NotImplementedError


__all__ = ["BaseLanguageHandler"]
