from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .database import DEFAULT_DATABASE_URL, persist_profiles, resolve_database_url
from .extractor import ProfileExtractor, TreeSitterDependencyError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build structural profiles for functions, methods, and classes using Tree-sitter, "
            "and emit a NetworkX-backed call graph."
        ),
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
    parser.add_argument(
        "--graph-root",
        type=Path,
        default=None,
        help=(
            "Base directory where call graph artifacts should be written. "
            "Defaults to the current working directory."
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

    call_graph = extractor.call_graph
    if call_graph is not None:
        graph_root = args.graph_root or Path.cwd()
        graph_dir = graph_root / "results" / "graphs"
        graph_dir.mkdir(parents=True, exist_ok=True)
        graph_path = graph_dir / "call_graph.json"
        payload = {
            "nodes": [
                {"id": node_id, **data}
                for node_id, data in call_graph.graph.nodes(data=True)
            ],
            "edges": call_graph.to_edge_index(),
            "unresolved_calls": sorted(call_graph.unresolved_calls),
        }
        graph_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote call graph to {graph_path}")

    return 0


def main() -> None:
    raise SystemExit(run())


__all__ = ["parse_args", "run", "main"]


if __name__ == "__main__":
    main()
