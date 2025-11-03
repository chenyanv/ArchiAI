from __future__ import annotations

import argparse
import sys
from typing import List, Tuple

from structural_scaffolding.pipeline.directory_tasks import (
    list_directories_for_summary,
    summarize_directory,
)


def _parse_args(argv: List[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate directory-level summaries using existing file (L1) summaries.",
    )
    parser.add_argument(
        "--database-url",
        help="Override STRUCTURAL_SCAFFOLD_DB_URL when connecting to Postgres.",
    )
    parser.add_argument(
        "--root-path",
        help="Restrict processing to the specified root_path recorded in the profiles table.",
    )
    parser.add_argument(
        "--directory",
        action="append",
        dest="directories",
        help="Summarise only the specified directory (relative path). May be passed multiple times.",
    )
    return parser.parse_args(argv)


def _directory_level(directory_path: str) -> int:
    if not directory_path or directory_path in {".", "./"}:
        return 0
    return len([segment for segment in directory_path.strip("/").split("/") if segment and segment != "."])


def _resolve_targets(args: argparse.Namespace) -> List[Tuple[str, str]]:
    if args.directories:
        root = args.root_path or ""
        targets = [(root, directory) for directory in args.directories]
    else:
        mapping = list_directories_for_summary(database_url=args.database_url, root_path=args.root_path)
        targets = []
        for root_path, directories in mapping.items():
            for directory in directories:
                targets.append((root_path, directory))

    return sorted(
        targets,
        key=lambda item: (item[0], -_directory_level(item[1]), item[1]),
    )


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv)
    targets = _resolve_targets(args)

    if not targets:
        print("No directories with file-level summaries were found.")
        return 0

    for root_path, directory in targets:
        display_root = root_path or "(unspecified)"
        print(f"Summarising directory {directory} (root={display_root})...", flush=True)
        try:
            result = summarize_directory(
                directory,
                root_path=root_path or None,
                database_url=args.database_url,
            )
        except Exception as exc:  # noqa: BLE001 - propagate context in CLI output
            print(f"  -> failed: {exc}", flush=True)
            continue

        if result is None:
            print("  -> skipped (no eligible context).", flush=True)
        else:
            print(
                f"  -> stored summary for {result['directory_path']} ({result['file_count']} files).",
                flush=True,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
