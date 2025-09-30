from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .database import DEFAULT_DATABASE_URL, persist_profiles, resolve_database_url
from .extractor import ProfileExtractor, TreeSitterDependencyError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build structural profiles for functions, methods, and classes using Tree-sitter.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to scan (defaults to current working directory).",
    )
    parser.add_argument(
        "--ignore",
        nargs="*",
        default=None,
        help="Optional list of directory names to ignore during traversal.",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help=(
            "SQLAlchemy database URL. Defaults to environment variable "
            "STRUCTURAL_SCAFFOLD_DB_URL or"
            f" {DEFAULT_DATABASE_URL}."
        ),
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        extractor = ProfileExtractor(
            root=args.root,
            ignored_dirs=args.ignore,
        )
        profiles = extractor.extract()
    except TreeSitterDependencyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    profiles.sort(key=lambda profile: profile.id)
    database_url = resolve_database_url(args.database_url)
    stored = persist_profiles(
        profiles,
        root=args.root,
        database_url=database_url,
    )

    print(f"Stored {stored} profiles into {database_url}")

    return 0


def main() -> None:
    raise SystemExit(run())


__all__ = ["parse_args", "run", "main"]
