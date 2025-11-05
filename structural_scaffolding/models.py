from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass(slots=True)
class CallSite:
    """Reference to a call expression within a profile body."""

    expression: str
    line: int
    context: Optional[str] = None


@dataclass(slots=True)
class ImportSite:
    """Metadata describing an import statement within a file."""

    module: Optional[str]
    name: Optional[str]
    alias: Optional[str]
    line: int
    level: int = 0
    is_star: bool = False

    @property
    def qualified(self) -> str:
        if self.module and self.name and not self.is_star:
            return f"{self.module}.{self.name}"
        if self.module:
            return self.module
        return self.name or ""


@dataclass(slots=True)
class UseSite:
    """Non-call dependency on another entity."""

    symbol: str
    use_kind: str
    line: int
    detail: Optional[str] = None


@dataclass(slots=True)
class InheritanceRef:
    """Link to a base class referenced in a class definition."""

    symbol: str
    line: int


@dataclass(slots=True)
class Profile:
    """Immutable structural profile for a function, method, or class."""

    id: str
    kind: str
    file_path: str
    function_name: Optional[str]
    class_name: Optional[str]
    start_line: int
    end_line: int
    source_code: str
    parent_id: Optional[str] = None
    docstring: Optional[str] = None
    parameters: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)
    call_sites: List[CallSite] = field(default_factory=list)
    import_sites: List[ImportSite] = field(default_factory=list)
    inheritance: List[InheritanceRef] = field(default_factory=list)
    uses: List[UseSite] = field(default_factory=list)
    children: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        # dataclasses.asdict preserves nested slots and ensures JSON serialization.
        return asdict(self)


__all__ = [
    "CallSite",
    "ImportSite",
    "InheritanceRef",
    "Profile",
    "UseSite",
]
