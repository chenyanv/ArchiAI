from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .extractor import ProfileExtractor, TreeSitterDependencyError, profiles_to_json


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
        "--output",
        type=Path,
        help="Optional output path for the generated JSON. Defaults to stdout when omitted.",
    )
    parser.add_argument(
        "--ignore",
        nargs="*",
        default=None,
        help="Optional list of directory names to ignore during traversal.",
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
    payload = profiles_to_json(profiles)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload)

    return 0


def main() -> None:
    raise SystemExit(run())


__all__ = ["parse_args", "run", "main"]
